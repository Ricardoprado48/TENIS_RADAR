"""Servico HTTP do LOTE H (docs/018_PWA_ARQUITETURA.md secao 22): expoe o
Forward Test (Fase 11) na PWA. So LE, organiza e apresenta o que
`src.forward` ja produziu -- nenhuma formula de resultado/settlement/paper
test/CLV/Brier/Log Loss/ROI/metrica acumulada e reimplementada aqui.

As unicas contas feitas nesta camada sao contagens/selecoes simples sobre
colunas ja calculadas (ex.: quantas previsoes tem `classification ==
"OBSERVAR"`) -- o mesmo tipo de agrupamento de apresentacao que
`src.forward.build.cumulative_dashboard`/`daily_report` ja fazem para o
relatorio em texto, so devolvido como JSON estruturado em vez de texto.
"""

from __future__ import annotations

import pandas as pd

from src.decision import config as decision_cfg
from src.forward import build as forward_build
from src.forward import config as fwd_cfg
from src.forward import metrics as fwd_metrics
from src.forward import odds_snapshots as fwd_snaps
from src.forward import paper_test as fwd_paper
from src.forward import predictions as fwd_preds
from src.forward import settlement as fwd_settle
from src.odds import config as odds_cfg

from api.schemas.forward import (
    CalibrationBucket,
    ClvInfo,
    ForwardResultCounts,
    ForwardSummaryCounts,
    ForwardSummaryResponse,
    ForwardTechnicalSummary,
    MarketTechnicalBreakdown,
    OddsHistory,
    PaperTestSummary,
    PredictionDetailResponse,
    PredictionListItem,
    PredictionListResponse,
    PredictionTechnicalDetails,
    RegisterForwardRequest,
    RegisterForwardResponse,
)

_TERMINAL_SETTLEMENTS = (fwd_cfg.SETTLEMENT_WIN, fwd_cfg.SETTLEMENT_LOSS, fwd_cfg.SETTLEMENT_VOID)
_CANDIDATE_CLASSIFICATIONS = ("CANDIDATO_FRACO", "CANDIDATO", "CANDIDATO_FORTE")

# item "MAPEAMENTO DE LINHAS" (mesma tecnica ja usada no LOTE G, secao 21):
# so escolhe qual coluna `odd_minima_{label}` ja congelada ler -- nunca
# recalcula `minimum_acceptable_odds`.
_EDGE_LABEL_TO_PCT = {v: k for k, v in odds_cfg.EDGE_STATUS_LABELS.items()}


class PredictionNotFoundError(LookupError):
    """`prediction_id` nao existe em `forward_predictions.parquet`."""


def _nan_to_none(value):
    if value is None:
        return None
    try:
        if value != value:  # NaN
            return None
    except TypeError:
        pass
    return value


def _minimum_odds_for_row(row: dict) -> float | None:
    floor_label = decision_cfg.MARKET_MIN_EDGE_LABEL.get(row.get("market"))
    pct = _EDGE_LABEL_TO_PCT.get(floor_label)
    if pct is None:
        return None
    return _nan_to_none(row.get(f"odd_minima_{pct}"))


def _settlement_by_prediction(settlements: pd.DataFrame) -> dict:
    if settlements.empty:
        return {}
    return {r["prediction_id"]: r for r in settlements.to_dict(orient="records")}


def get_summary() -> ForwardSummaryResponse:
    predictions = fwd_preds.load_predictions()
    settlements = fwd_settle.latest_settlements()
    settled_by_id = _settlement_by_prediction(settlements)

    if predictions.empty:
        counts = ForwardSummaryCounts(
            n_predictions_registered=0, n_pending_settlement=0, n_resolved=0,
            n_candidates=0, n_observar=0, n_descartados=0,
        )
        results = ForwardResultCounts(wins=0, losses=0, void=0, pending=0)
    else:
        cls_counts = predictions["classification"].value_counts()
        n_total = int(len(predictions))
        settlement_values = [
            settled_by_id.get(pid, {}).get("settlement", fwd_cfg.SETTLEMENT_UNRESOLVED)
            for pid in predictions["prediction_id"]
        ]
        n_resolved = sum(1 for s in settlement_values if s in _TERMINAL_SETTLEMENTS)

        counts = ForwardSummaryCounts(
            n_predictions_registered=n_total,
            n_pending_settlement=n_total - n_resolved,
            n_resolved=n_resolved,
            n_candidates=int(sum(int(cls_counts.get(c, 0)) for c in _CANDIDATE_CLASSIFICATIONS)),
            n_observar=int(cls_counts.get("OBSERVAR", 0)),
            n_descartados=int(cls_counts.get("DESCARTAR", 0)),
        )
        wins = sum(1 for s in settlement_values if s == fwd_cfg.SETTLEMENT_WIN)
        losses = sum(1 for s in settlement_values if s == fwd_cfg.SETTLEMENT_LOSS)
        void = sum(1 for s in settlement_values if s == fwd_cfg.SETTLEMENT_VOID)
        results = ForwardResultCounts(wins=wins, losses=losses, void=void, pending=n_total - wins - losses - void)

    paper_df = pd.read_parquet(fwd_cfg.PAPER_TEST_PATH) if fwd_cfg.PAPER_TEST_PATH.exists() else pd.DataFrame()
    paper_summary = fwd_paper.summarize_paper_test(paper_df)
    paper_test = PaperTestSummary(**paper_summary)

    technical = _build_technical_summary(predictions, settlements)

    return ForwardSummaryResponse(counts=counts, results=results, paper_test=paper_test, technical=technical)


def _build_technical_summary(predictions: pd.DataFrame, settlements: pd.DataFrame) -> ForwardTechnicalSummary:
    df = fwd_metrics.with_outcome(predictions, settlements)
    if df.empty:
        return ForwardTechnicalSummary()

    bucket_df = fwd_metrics.calibration_by_bucket(df)
    bucket_rows = bucket_df[bucket_df["n"] > 0] if not bucket_df.empty else bucket_df
    calibration = [
        CalibrationBucket(
            bucket=str(r["bucket"]), n=int(r["n"]),
            mean_predicted=_nan_to_none(r.get("mean_predicted")),
            observed_rate=_nan_to_none(r.get("observed_rate")),
        )
        for r in bucket_rows.to_dict(orient="records")
    ] if not bucket_rows.empty else []

    paper_df = pd.read_parquet(fwd_cfg.PAPER_TEST_PATH) if fwd_cfg.PAPER_TEST_PATH.exists() else pd.DataFrame()
    clv_df = pd.read_parquet(fwd_cfg.CLV_ANALYSIS_PATH) if fwd_cfg.CLV_ANALYSIS_PATH.exists() else pd.DataFrame()

    by_market = []
    for market in sorted(predictions["market"].dropna().unique()):
        m_df = df[df["market"] == market]
        m_paper = paper_df[paper_df["market"] == market] if not paper_df.empty else paper_df
        m_paper_resolved = m_paper[m_paper["pnl_units"].notna()] if not m_paper.empty else m_paper
        m_clv = clv_df[clv_df["market"] == market] if not clv_df.empty else clv_df

        n = int(len(m_df))
        roi = (
            float(m_paper_resolved["pnl_units"].sum() / len(m_paper_resolved))
            if not m_paper_resolved.empty else None
        )
        by_market.append(MarketTechnicalBreakdown(
            market=market, n=n,
            brier_score=fwd_metrics.brier_score(m_df) if n else None,
            clv_avg_pct=float(m_clv["clv_pct"].mean()) if not m_clv.empty else None,
            paper_roi=roi,
        ))

    return ForwardTechnicalSummary(
        brier_score_overall=_nan_to_none(fwd_metrics.brier_score(df)),
        log_loss_overall=_nan_to_none(fwd_metrics.log_loss(df)),
        calibration=calibration,
        by_market=by_market,
    )


def list_predictions(
    *, tour: str | None, settlement_group: str | None, classification_group: str | None,
    limit: int, offset: int,
) -> PredictionListResponse:
    predictions = fwd_preds.load_predictions()
    if predictions.empty:
        return PredictionListResponse(items=[], total=0, limit=limit, offset=offset)

    settled_by_id = _settlement_by_prediction(fwd_settle.latest_settlements())

    df = predictions.copy()
    df["settlement"] = [
        settled_by_id.get(pid, {}).get("settlement", fwd_cfg.SETTLEMENT_UNRESOLVED) for pid in df["prediction_id"]
    ]
    df["settlement_reason"] = [settled_by_id.get(pid, {}).get("settlement_reason") for pid in df["prediction_id"]]

    if tour:
        df = df[df["tour"] == tour]
    if classification_group == "candidato":
        df = df[df["classification"].isin(_CANDIDATE_CLASSIFICATIONS)]
    elif classification_group == "observar":
        df = df[df["classification"] == "OBSERVAR"]
    elif classification_group == "descartado":
        df = df[df["classification"] == "DESCARTAR"]
    if settlement_group == "pendentes":
        df = df[~df["settlement"].isin(_TERMINAL_SETTLEMENTS)]
    elif settlement_group == "resolvidas":
        df = df[df["settlement"].isin(_TERMINAL_SETTLEMENTS)]

    df = df.sort_values("registered_at", ascending=False)
    total = int(len(df))
    page = df.iloc[offset: offset + limit]

    items = [
        PredictionListItem(
            prediction_id=r["prediction_id"], registered_at=r["registered_at"], tour=r["tour"],
            tournament=_nan_to_none(r.get("tournament")), player=_nan_to_none(r.get("player")),
            opponent=_nan_to_none(r.get("opponent")),
            market=r["market"], side=r["side"], line=r["line"], decimal_odds=r["decimal_odds"],
            classification=r["classification"], settlement=r["settlement"],
            settlement_reason=_nan_to_none(r.get("settlement_reason")),
        )
        for r in page.to_dict(orient="records")
    ]
    return PredictionListResponse(items=items, total=total, limit=limit, offset=offset)


def get_prediction_detail(prediction_id: str) -> PredictionDetailResponse:
    predictions = fwd_preds.load_predictions()
    if predictions.empty:
        raise PredictionNotFoundError(prediction_id)
    matches = predictions[predictions["prediction_id"] == prediction_id]
    if matches.empty:
        raise PredictionNotFoundError(prediction_id)
    row = matches.iloc[-1].to_dict()

    settlements = fwd_settle.latest_settlements()
    s = None
    if not settlements.empty:
        srows = settlements[settlements["prediction_id"] == prediction_id]
        if not srows.empty:
            s = srows.iloc[-1].to_dict()
    settlement = s["settlement"] if s else fwd_cfg.SETTLEMENT_UNRESOLVED
    settlement_reason = s.get("settlement_reason") if s else None
    settled_at = s.get("settled_at") if s else None

    paper_df = pd.read_parquet(fwd_cfg.PAPER_TEST_PATH) if fwd_cfg.PAPER_TEST_PATH.exists() else pd.DataFrame()
    paper_row = None
    if not paper_df.empty:
        pr = paper_df[paper_df["prediction_id"] == prediction_id]
        if not pr.empty:
            paper_row = pr.iloc[-1].to_dict()

    clv_df = pd.read_parquet(fwd_cfg.CLV_ANALYSIS_PATH) if fwd_cfg.CLV_ANALYSIS_PATH.exists() else pd.DataFrame()
    clv_row = None
    if not clv_df.empty:
        cr = clv_df[clv_df["prediction_id"] == prediction_id]
        if not cr.empty:
            clv_row = cr.iloc[-1].to_dict()

    odds_history = None
    movement_df = fwd_snaps.summarize_odds_movement()
    if not movement_df.empty:
        mv = movement_df[movement_df["prediction_id"] == prediction_id]
        if not mv.empty:
            m = mv.iloc[-1].to_dict()
            odds_history = OddsHistory(
                n_snapshots=int(m["n_snapshots"]),
                first_observed_odds=_nan_to_none(m.get("first_observed_odds")),
                last_observed_odds=_nan_to_none(m.get("last_observed_odds")),
                best_observed_odds=_nan_to_none(m.get("best_observed_odds")),
                closing_odds_observed=_nan_to_none(m.get("closing_odds_observed")),
                closing_odds_note=m.get("closing_odds_note"),
            )

    clv_info = (
        ClvInfo(clv_pct=_nan_to_none(clv_row.get("clv_pct")), clv_probability_diff=_nan_to_none(clv_row.get("clv_probability_diff")))
        if clv_row is not None else None
    )

    reasons = row.get("reasons")
    alerts = row.get("alerts")
    technical = PredictionTechnicalDetails(
        implied_probability=_nan_to_none(row.get("implied_probability")),
        model_edge=_nan_to_none(row.get("model_edge")),
        sample_quality=_nan_to_none(row.get("sample_quality")),
        method_selected=_nan_to_none(row.get("method_selected")),
        restricted=bool(row.get("restricted")) if row.get("restricted") == row.get("restricted") else False,
        restricted_motivo=_nan_to_none(row.get("restricted_motivo")),
        staleness_bucket=_nan_to_none(row.get("staleness_bucket")),
        data_staleness_days=_nan_to_none(row.get("data_staleness_days")),
        historical_data_cutoff=_nan_to_none(row.get("historical_data_cutoff")),
        reasons=[r for r in str(reasons).split(" | ") if r] if reasons else [],
        alerts=[a for a in str(alerts).split(" | ") if a] if alerts else [],
    )

    return PredictionDetailResponse(
        prediction_id=row["prediction_id"], registered_at=row["registered_at"], tour=row["tour"],
        tournament=_nan_to_none(row.get("tournament")), match_id=row["match_id"],
        player=_nan_to_none(row.get("player")), opponent=_nan_to_none(row.get("opponent")),
        surface_ctx=_nan_to_none(row.get("surface_ctx")), market=row["market"],
        side=row["side"], line=row["line"],
        operational_probability=_nan_to_none(row.get("operational_probability")),
        fair_odds=_nan_to_none(row.get("fair_odds")), minimum_odds=_minimum_odds_for_row(row),
        decimal_odds=row["decimal_odds"], bookmaker=row["bookmaker"],
        classification=row["classification"], settlement=settlement,
        settlement_reason=settlement_reason, settled_at=settled_at,
        paper_result_units=_nan_to_none(paper_row.get("pnl_units")) if paper_row is not None else None,
        paper_test_label=paper_row.get("test_label") if paper_row is not None else None,
        odds_history=odds_history, clv=clv_info, technical=technical,
    )


_REGISTER_MESSAGES = {
    "registered": "Registrado no Forward Test.",
    "already_registered": "Ja registrado no Forward Test.",
    "not_found": "Oportunidade nao encontrada na Fase 10 -- avalie novamente antes de registrar.",
    "rejected_overwrite_attempt": "Registro rejeitado: valores diferentes de um registro ja existente para esta oportunidade.",
}


def register_prediction(payload: RegisterForwardRequest) -> RegisterForwardResponse:
    forward_key = {
        "bookmaker": payload.bookmaker, "tour": payload.tour, "match_id": payload.match_id,
        "market": payload.market, "player": payload.player, "side": payload.side,
        "line": payload.line, "decimal_odds": payload.decimal_odds, "collected_at": payload.collected_at,
    }
    result = forward_build.register_opportunity(forward_key)
    return RegisterForwardResponse(
        status=result["status"], prediction_id=result.get("prediction_id"),
        message=_REGISTER_MESSAGES[result["status"]],
    )
