"""Orquestrador da Fase 11 (forward test). Cada funcao publica corresponde a
um comando do CLI (item 17): `register_day` / `record_odds_for_prediction` /
`record_match_result` / `settle_day` / `daily_report` / `cumulative_dashboard`
/ `run_forward_day`.

Nao re-treina, nao recalibra, nao re-seleciona mercado, nao calcula stake
real, nao faz aposta, nao cria interface, nao avanca para a Fase 12."""

from __future__ import annotations

import json

import pandas as pd

from . import clv
from . import config as cfg
from . import ids
from . import inputs
from . import labels as lbl
from . import metrics
from . import odds_snapshots as snaps
from . import paper_test as pt
from . import predictions as preds
from . import results as res
from . import settlement as settle


def register_day(classifications: list[str] | None = None) -> dict:
    """item 3/4: registra TODAS as oportunidades ja classificadas pela Fase
    10 que ainda nao foram registradas -- inclusive DESCARTAR."""

    cfg.PHASE11_DIR.mkdir(parents=True, exist_ok=True)
    opportunities = inputs.load_opportunities_for_registration(classifications)
    result = preds.register_predictions(opportunities)

    # item 5: a odd usada no registro tambem conta como o primeiro snapshot.
    added = result["added"]
    if not added.empty:
        first_snaps = added[["prediction_id", "bookmaker", "decimal_odds", "collected_at"]].copy()
        first_snaps["snapshot_id"] = [
            ids.make_snapshot_id(pid, at) for pid, at in zip(first_snaps["prediction_id"], first_snaps["collected_at"])
        ]
        snaps.append_snapshots(first_snaps)

    return {
        "n_registered": int(len(added)),
        "n_skipped_duplicates": len(result["skipped_duplicates"]),
        "n_rejected_overwrite_attempts": len(result["rejected_overwrite_attempts"]),
        "rejected_overwrite_attempts": result["rejected_overwrite_attempts"],
    }


def register_opportunity(forward_key: dict) -> dict:
    """LOTE H (PWA, docs/018 secao 22): registra UMA oportunidade especifica
    -- nunca em lote (isso e o que `register_day` faz, item 3/4). Disparado
    so pelo clique explicito de "Registrar no Forward Test" na tela de
    avaliacao (LOTE G), nunca automaticamente.

    `forward_key` identifica a oportunidade pela MESMA chave natural que a
    Fase 9/10 ja usa: bookmaker, tour, match_id, market, player, side, line,
    decimal_odds, collected_at. Reaproveita inteiramente
    `inputs.load_opportunities_for_registration` (o mesmo join usado por
    `register_day`) + `predictions.register_predictions` (mesma
    imutabilidade/dedup, item 1) -- nenhuma logica nova de registro."""

    cfg.PHASE11_DIR.mkdir(parents=True, exist_ok=True)

    pid = ids.make_prediction_id(
        forward_key.get("bookmaker"), forward_key.get("tour"), forward_key.get("match_id"),
        forward_key.get("market"), forward_key.get("player"), forward_key.get("side"), forward_key.get("line"),
    )

    opportunities = inputs.load_opportunities_for_registration()
    if opportunities.empty:
        return {"status": "not_found", "prediction_id": pid}

    mask = (
        (opportunities["bookmaker"] == forward_key.get("bookmaker"))
        & (opportunities["tour"] == forward_key.get("tour"))
        & (opportunities["match_id"] == forward_key.get("match_id"))
        & (opportunities["market"] == forward_key.get("market"))
        & (opportunities["player"] == forward_key.get("player"))
        & (opportunities["side"] == forward_key.get("side"))
        & (opportunities["line"] == float(forward_key.get("line")))
        & (opportunities["decimal_odds"] == float(forward_key.get("decimal_odds")))
    )
    collected_at = forward_key.get("collected_at")
    if collected_at and "collected_at" in opportunities.columns:
        target = pd.to_datetime(collected_at, format="mixed", utc=True)
        observed = pd.to_datetime(opportunities["collected_at"], format="mixed", utc=True, errors="coerce")
        mask &= observed == target

    subset = opportunities[mask]
    if subset.empty:
        return {"status": "not_found", "prediction_id": pid}
    subset = subset.tail(1)  # chave completa e unica na pratica; nunca escolhe "a errada" silenciosamente em duplicidade

    result = preds.register_predictions(subset)
    added = result["added"]

    # item 5: a odd usada no registro tambem conta como o primeiro
    # snapshot -- mesma logica de `register_day`.
    if not added.empty:
        first_snaps = added[["prediction_id", "bookmaker", "decimal_odds", "collected_at"]].copy()
        first_snaps["snapshot_id"] = [
            ids.make_snapshot_id(p, at) for p, at in zip(first_snaps["prediction_id"], first_snaps["collected_at"])
        ]
        snaps.append_snapshots(first_snaps)
        return {"status": "registered", "prediction_id": pid}

    if result["rejected_overwrite_attempts"]:
        return {
            "status": "rejected_overwrite_attempt", "prediction_id": pid,
            "rejected": result["rejected_overwrite_attempts"][0],
        }

    return {"status": "already_registered", "prediction_id": pid}


def is_registered(prediction_id: str) -> bool:
    predictions = preds.load_predictions()
    if predictions.empty:
        return False
    return bool((predictions["prediction_id"] == prediction_id).any())


def record_odds_for_prediction(prediction_id: str, bookmaker: str, decimal_odds: float, collected_at: str | None = None) -> pd.DataFrame:
    return snaps.record_snapshot(prediction_id, bookmaker, decimal_odds, collected_at)


def record_match_result(entry: dict) -> dict:
    return res.record_result(entry)


def settle_day() -> dict:
    predictions = preds.load_predictions()
    results = res.load_results()
    settle_result = settle.settle_all(predictions, results)

    odds_movement = snaps.summarize_odds_movement()
    clv_df = clv.compute_clv(predictions, odds_movement) if not odds_movement.empty else pd.DataFrame()

    latest_settlements = settle.latest_settlements()
    paper_df = pt.build_paper_test(predictions, latest_settlements)
    paper_summary = pt.summarize_paper_test(paper_df)

    df_with_outcome = metrics.with_outcome(predictions, latest_settlements)
    metrics.build_forward_metrics(predictions, latest_settlements)
    threshold_df = metrics.threshold_comparison(df_with_outcome, paper_df)
    classification_df = metrics.classification_comparison(predictions, latest_settlements, paper_df)
    checkpoints = metrics.sample_size_checkpoints(int(len(predictions)))

    summary = {
        "n_predictions_total": int(len(predictions)),
        "n_new_settlement_events": int(len(settle_result["new_events"])),
        "n_rejected_settlement_overwrites": len(settle_result["rejected_overwrite_attempts"]),
        "rejected_settlement_overwrites": settle_result["rejected_overwrite_attempts"],
        "paper_test_summary": paper_summary,
        "sample_size_checkpoints": checkpoints,
        "threshold_comparison": threshold_df.to_dict(orient="records") if not threshold_df.empty else [],
        "classification_comparison": classification_df.to_dict(orient="records") if not classification_df.empty else [],
        "n_clv_rows": int(len(clv_df)),
    }
    cfg.PHASE11_DIR.mkdir(parents=True, exist_ok=True)
    with open(cfg.PHASE11_SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str, ensure_ascii=False)
    return summary


def daily_report(date_label: str | None = None) -> str:
    """item 18: relatorio diario legivel (area "HOJE / TODAY"). `partidas
    analisadas` conta so as partidas com oportunidade ja registrada nesta
    fase (limitacao registrada em docs/017 -- ainda depende de odds
    coletadas manualmente, Fase 9). Apresentacao bilingue PT/EN via
    `labels.py` -- nenhuma probabilidade/odd/edge/classificacao e
    recalculada aqui, so formatada."""

    predictions = preds.load_predictions()
    settlements = settle.latest_settlements()
    date_label = date_label or pd.Timestamp.now("UTC").date().isoformat()
    header = f"HOJE / TODAY -- {date_label}"

    if predictions.empty:
        return f"{header}\n\nNenhuma previsao registrada ainda. / No predictions registered yet."

    reg_dates = pd.to_datetime(predictions["registered_at"], format="mixed", utc=True).dt.date.astype(str)
    today = predictions[reg_dates == date_label]
    if today.empty:
        return f"{header}\n\nNenhuma previsao registrada nesta data. / No predictions registered on this date."

    n_odds = int(today["decimal_odds"].notna().sum())
    candidates = today[today["classification"].isin(["CANDIDATO", "CANDIDATO_FORTE", "CANDIDATO_FRACO"])]

    lines = [
        header, "",
        f"Partidas analisadas / Matches analyzed: {today['match_id'].nunique()}",
        f"Odds registradas / Bookmaker odds recorded: {n_odds}",
        f"Candidatos / Candidates: {len(candidates)}",
        "",
    ]
    settled_by_id = (
        {r["prediction_id"]: r for r in settlements.to_dict(orient="records")} if not settlements.empty else {}
    )

    for _match_id, group in today.groupby("match_id", sort=False):
        first = group.iloc[0]
        lines += [
            "-" * 64,
            f"{lbl.fmt_text(first.get('tournament'))}  ({lbl.tour_label(first.get('tour'))})",
            f"Superficie / Surface: {lbl.surface_label(first.get('surface_ctx'))}",
            f"Data / Date: {date_label}",
            f"{lbl.fmt_text(first.get('player'))} x {lbl.fmt_text(first.get('opponent'))}",
            "-" * 64,
            "",
        ]
        for row in group.to_dict(orient="records"):
            s = settled_by_id.get(row["prediction_id"])
            result_key = s["settlement"] if s else cfg.SETTLEMENT_UNRESOLVED
            player_suffix = (
                f" -- {lbl.fmt_text(row.get('player'))}" if row.get("market") != "total_aces_match" else ""
            )
            lines += [
                f"  Mercado / Market: {lbl.market_label(row.get('market'))}{player_suffix}",
                f"  Linha / Line: {lbl.side_label(row.get('side'))} {lbl.fmt_line(row.get('line'))}",
                f"  Probabilidade do modelo / Model Probability: {lbl.fmt_pct(row.get('operational_probability'))}",
                f"  Odd justa / Fair Odds: {lbl.fmt_odds(row.get('fair_odds'))}",
                f"  Odd encontrada / Bookmaker Odds: {lbl.fmt_odds(row.get('decimal_odds'))}",
                f"  Edge: {lbl.fmt_edge_pp(row.get('model_edge'))}",
                f"  Classificacao / Classification: {lbl.classification_label(row.get('classification'))}",
                f"  Resultado / Result: {lbl.settlement_label(result_key)}",
                "",
            ]
    return "\n".join(lines)


def _hit_rate_line(label: str, subset: pd.DataFrame) -> str:
    if subset.empty:
        return f"{label}: sem previsoes com resultado definido / no settled predictions"
    hit_rate = float(subset["outcome"].mean())
    return f"{label}: N={len(subset)} | acerto observado / observed hit rate: {lbl.fmt_pct(hit_rate)}"


def cumulative_dashboard() -> str:
    """item 19: resumo cumulativo (area "DESEMPENHO HISTORICO / HISTORICAL
    PERFORMANCE"), sempre com o tamanho da amostra. Linguagem simples no
    corpo principal (contagem + taxa de acerto observada por ano/tour/
    superficie + calibracao em frases); metricas tecnicas (Brier, Log Loss,
    CLV, Paper ROI) isoladas na subsecao "DETALHES TECNICOS" para nao
    confundir quem so quer o resumo. Nenhuma metrica e recalculada aqui --
    tudo vem de `metrics.py`/`clv.py`/`paper_test.py`, ja calculados."""

    predictions = preds.load_predictions()
    header = "DESEMPENHO HISTORICO / HISTORICAL PERFORMANCE"
    if predictions.empty:
        return f"{header}\n\nAmostra / Sample: 0\n\nNenhuma previsao registrada ainda. / No predictions registered yet."

    settlements = settle.latest_settlements()
    df = metrics.with_outcome(predictions, settlements)
    paper_df = pd.read_parquet(cfg.PAPER_TEST_PATH) if cfg.PAPER_TEST_PATH.exists() else pd.DataFrame()
    clv_df = pd.read_parquet(cfg.CLV_ANALYSIS_PATH) if cfg.CLV_ANALYSIS_PATH.exists() else pd.DataFrame()

    lines = [
        header, "",
        f"Numero de previsoes historicas / Number of historical predictions: {len(predictions)}",
        "",
    ]

    if df.empty:
        lines += [
            "Ainda nao ha previsoes com resultado definido (WIN/LOSS) para medir desempenho.",
            "No settled (WIN/LOSS) predictions yet to measure performance.",
            "",
        ]
    else:
        reg_year = pd.to_datetime(df["registered_at"], format="mixed", utc=True).dt.year

        lines.append("--- Desempenho por ano / Performance by year ---")
        for year in [2024, 2025, 2026]:
            lines.append(_hit_rate_line(str(year), df[reg_year == year]))
        other_years = sorted(set(reg_year.dropna().astype(int)) - {2024, 2025, 2026})
        for year in other_years:
            lines.append(_hit_rate_line(str(year), df[reg_year == year]))
        lines.append("")

        lines.append("--- ATP / WTA ---")
        for tour in ["ATP", "WTA"]:
            lines.append(_hit_rate_line(lbl.tour_label(tour), df[df["tour"] == tour]))
        lines.append("")

        lines.append("--- Superficie / Surface ---")
        for surface_key in ["hard", "clay", "grass"]:
            subset = df[df["surface_ctx"].astype(str).str.lower() == surface_key]
            lines.append(_hit_rate_line(lbl.bilingual(lbl.SURFACE_LABELS, surface_key), subset))
        lines.append("")

        lines.append("--- Calibracao em linguagem simples / Calibration in plain language ---")
        bucket_df = metrics.calibration_by_bucket(df)
        bucket_rows = bucket_df[bucket_df["n"] > 0] if not bucket_df.empty else bucket_df
        if bucket_rows.empty:
            lines.append("Amostra ainda insuficiente para avaliar calibracao. / Sample still too small to assess calibration.")
        else:
            for row in bucket_rows.to_dict(orient="records"):
                lines.append(
                    f"Quando o modelo previu {row['bucket']} de chance (N={int(row['n'])}), "
                    f"o resultado aconteceu em {lbl.fmt_pct(row['observed_rate'])} dos casos. / "
                    f"When the model predicted {row['bucket']} probability (N={int(row['n'])}), "
                    f"the outcome happened {lbl.fmt_pct(row['observed_rate'])} of the time."
                )
        lines.append("")

    lines.append("DETALHES TECNICOS / TECHNICAL DETAILS")
    lines.append("")
    if df.empty:
        lines.append("Sem previsoes com resultado definido. / No settled predictions.")
    else:
        overall_brier = metrics.brier_score(df)
        overall_log_loss = metrics.log_loss(df)
        lines += [
            f"Brier Score (geral / overall): {lbl.fmt_number(overall_brier)}",
            f"Log Loss (geral / overall): {lbl.fmt_number(overall_log_loss)}",
            "",
            "--- Por mercado / By market ---",
        ]
        for market in sorted(predictions["market"].dropna().unique()):
            m_df = df[df["market"] == market] if not df.empty else df
            m_paper = paper_df[paper_df["market"] == market] if not paper_df.empty else paper_df
            m_paper_resolved = m_paper[m_paper["pnl_units"].notna()] if not m_paper.empty else m_paper
            m_clv = clv_df[clv_df["market"] == market] if not clv_df.empty else clv_df

            n = int(len(m_df))
            brier = metrics.brier_score(m_df) if n else None
            roi = (
                float(m_paper_resolved["pnl_units"].sum() / len(m_paper_resolved))
                if not m_paper_resolved.empty else None
            )
            clv_mean = float(m_clv["clv_pct"].mean()) if not m_clv.empty else None

            lines += [
                f"{lbl.market_label(market)}:",
                f"  N = {n}",
                f"  Brier = {lbl.fmt_number(brier)}" if brier is not None else "  Brier = N/A (amostra insuficiente / insufficient sample)",
                f"  CLV medio / average CLV = {lbl.fmt_signed_pct(clv_mean)}" if clv_mean is not None else "  CLV medio / average CLV = N/A",
                (
                    f"  Paper ROI = {lbl.fmt_signed_pct(roi)}" if roi is not None
                    else "  Paper ROI = N/A (sem entradas resolvidas / no resolved entries)"
                ),
                "",
            ]
    return "\n".join(lines)


def run_forward_day() -> dict:
    """item 17: comando agregador -- registra + settle + reports; nunca
    exige bookmaker automatico (odds continuam manuais, Fase 9)."""

    register_result = register_day()
    settle_result = settle_day()
    return {
        "register": register_result,
        "settle": settle_result,
        "daily_report": daily_report(),
        "cumulative_dashboard": cumulative_dashboard(),
    }
