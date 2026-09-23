"""Orquestrador da Fase 8: partidas futuras -> jogadores resolvidos ->
features point-in-time -> lambda/r -> probabilidade calibrada -> odd
justa/minima -> radar diario. Nenhum passo recalcula um modelo ja definido
nas Fases 3-7; ver docstrings de cada submodulo para o que exatamente e
reaproveitado de onde."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.normalization.players import load_players

from . import candidates as cand
from . import config as cfg
from . import calibration_future as calib
from . import features_future as feat
from . import identity as ident
from . import pricing_future as pricing
from . import probabilities_future as probs
from . import rates_future as rates
from . import sources


def _load_players_by_tour() -> dict[str, pd.DataFrame]:
    out = {}
    for tour_lower in ("atp", "wta"):
        players, _n_dup = load_players(tour_lower)
        out[players["tour"].iloc[0]] = players
    return out


def _match_context(resolved: pd.DataFrame) -> pd.DataFrame:
    ctx = resolved[resolved["usable_for_prediction"] & ~resolved["is_duplicate"]].copy()
    ctx["match_id"] = [
        f"FUTURE:{t}:{s}" for t, s in zip(ctx["tour"], ctx["raw_match_seq"])
    ]
    return ctx[[
        "match_id", "tournament", "surface", "match_date", "round",
        "player_id_a", "player_id_b", "resolved_name_a", "resolved_name_b",
        "resolution_method_a", "resolution_method_b",
    ]]


def _enrich_with_match_context(df: pd.DataFrame, ctx: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.merge(ctx, on="match_id", how="left", suffixes=("", "_ctx"))
    is_a = out["player_id"] == out["player_id_a"]
    out["player_name"] = np.where(is_a, out["resolved_name_a"], out["resolved_name_b"])
    out["opponent_name"] = np.where(is_a, out["resolved_name_b"], out["resolved_name_a"])
    out["resolution_method_player"] = np.where(is_a, out["resolution_method_a"], out["resolution_method_b"])
    out["resolution_method_opponent"] = np.where(is_a, out["resolution_method_b"], out["resolution_method_a"])
    return out.drop(columns=["player_id_a", "player_id_b", "resolved_name_a", "resolved_name_b",
                              "resolution_method_a", "resolution_method_b"])


def _build_future_rows_all_tours(resolved: pd.DataFrame, historical_overrides: dict | None = None) -> pd.DataFrame:
    parts = []
    for tour in cfg.TOURS:
        resolved_tour = resolved[resolved["tour"] == tour]
        override_path = (historical_overrides or {}).get(tour)
        fr = feat.build_future_feature_rows(tour, resolved_tour, override_path=override_path)
        if fr.empty:
            continue
        fr = rates.add_all_predictions(fr)
        parts.append(fr)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def _unresolved_players_log(resolved: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in resolved.itertuples(index=False):
        for side, raw_name, method, note in [
            ("A", r.player_a_raw, r.resolution_method_a, r.resolution_note_a),
            ("B", r.player_b_raw, r.resolution_method_b, r.resolution_note_b),
        ]:
            if method in ("unresolved", "fuzzy_review"):
                rows.append({
                    "tour": r.tour, "tournament": r.tournament, "match_date": r.match_date,
                    "round": r.round, "side": side, "raw_name": raw_name,
                    "resolution_method": method, "note": note,
                    "raw_match_seq": r.raw_match_seq,
                })
    return pd.DataFrame(rows)


def _data_staleness_report(resolved: pd.DataFrame, historical_overrides: dict | None = None) -> dict:
    out = {}
    for tour in cfg.TOURS:
        override_path = (historical_overrides or {}).get(tour)
        hist = feat.load_historical_matches(tour, override_path)
        max_hist_date = hist["tournament_date"].max()
        matches_this_tour = resolved[resolved["tour"] == tour]
        if matches_this_tour.empty:
            continue
        min_future_date = matches_this_tour["match_date"].min()
        gap_days = (pd.Timestamp(min_future_date) - pd.Timestamp(max_hist_date)).days
        out[tour] = {
            "max_historical_match_date": str(max_hist_date.date()),
            "min_future_match_date": str(pd.Timestamp(min_future_date).date()),
            "gap_days": int(gap_days),
        }
    return out


def run(raw_path: str | None = None, historical_overrides: dict | None = None, output_dir=None) -> dict:
    """`historical_overrides` (opcional): {"ATP": Path, "WTA": Path} para
    rodar o radar contra uma base historica alternativa (Fase 8.1), sem
    tocar em `data/processed/`. `output_dir` (opcional): onde gravar as
    saidas quando `historical_overrides` for usado (nunca sobrescreve
    `data/outputs/phase8/` da Fase 8 original)."""

    out_dir = output_dir or cfg.PHASE8_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = sources.load_raw_matches(raw_path)
    players_by_tour = _load_players_by_tour()

    resolved = ident.resolve_matches(raw, players_by_tour)
    resolved = ident.flag_duplicate_matches(resolved)

    raw.to_parquet(out_dir / "partidas_futuras_brutas.parquet", index=False)
    raw.to_csv(out_dir / "partidas_futuras_brutas.csv", index=False)
    resolved.to_parquet(out_dir / "partidas_resolvidas.parquet", index=False)
    resolved.to_csv(out_dir / "partidas_resolvidas.csv", index=False)

    unresolved_log = _unresolved_players_log(resolved)
    unresolved_log.to_csv(out_dir / "jogadores_nao_resolvidos.csv", index=False)

    future_rows = _build_future_rows_all_tours(resolved, historical_overrides)

    configs = probs.load_market_configs()
    cd_df = probs.load_count_distribution_metrics()
    predictions = probs.build_predictions_by_line(future_rows, configs, cd_df)
    predictions.to_parquet(out_dir / "previsoes_por_partida.parquet", index=False)

    phase6_df = pd.read_parquet(
        cfg.PHASE6_PREDICTIONS_PATH, columns=["tour", "market", "fold", "p_over_negbin", "actual_over"],
    )
    calibrators = calib.build_calibrators(phase6_df)
    calibrated = calib.apply_calibration(predictions, calibrators)

    base, prices, min_odds = pricing.build_price_tables(calibrated)

    ctx = _match_context(resolved)
    prices_enriched = _enrich_with_match_context(prices, ctx)
    min_odds_enriched = _enrich_with_match_context(min_odds, ctx)

    prices_with_candidates = cand.flag_candidates(prices_enriched) if not prices_enriched.empty else prices_enriched
    if not prices_with_candidates.empty:
        prices_with_candidates.to_parquet(out_dir / "precos_por_linha.parquet", index=False)
        prices_with_candidates.to_csv(out_dir / "precos_por_linha.csv", index=False)
    if not min_odds_enriched.empty:
        min_odds_enriched.to_parquet(out_dir / "odds_minimas_por_edge.parquet", index=False)
        min_odds_enriched.to_csv(out_dir / "odds_minimas_por_edge.csv", index=False)

    daily_summary = cand.build_daily_summary(prices_with_candidates, resolved) if not prices_with_candidates.empty else pd.DataFrame()
    daily_summary.to_csv(out_dir / "radar_diario_resumo.csv", index=False)

    staleness = _data_staleness_report(resolved, historical_overrides)

    summary = {
        "collected_at": str(raw["collected_at"].max()) if not raw.empty else None,
        "n_matches_raw": int(len(raw)),
        "n_matches_resolved_usable": int(resolved["usable_for_prediction"].sum()),
        "n_matches_unresolved": int((~resolved["usable_for_prediction"]).sum()),
        "n_matches_duplicate": int(resolved["is_duplicate"].sum()),
        "n_prediction_rows": int(len(predictions)),
        "n_price_rows": int(len(prices_with_candidates)) if not prices_with_candidates.empty else 0,
        "n_radar_candidates": int(daily_summary["is_radar_candidate"].sum()) if not daily_summary.empty else 0,
        "data_staleness": staleness,
        "edge_levels": cfg.EDGE_LEVELS,
        "current_fold_used_for_negbin_r_and_calibration": cfg.CURRENT_FOLD,
    }
    with open(out_dir / "phase8_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    return summary
