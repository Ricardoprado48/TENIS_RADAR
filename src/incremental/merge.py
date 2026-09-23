"""Integra partidas incrementais na base historica SEM sobrescrever
`data/processed/{tour}/` (Fase 2) -- a base combinada, quando ha partidas
novas, e gravada em `data/processed/incremental_2026/{tour}/matches.parquet`
(item 3 e item 6 da instrucao: preservacao + mesmo motor da Fase 3)."""

from __future__ import annotations

import pandas as pd

from src.features.matchup import build_matchup_table
from src.features.profile import build_player_profile
from src.normalization.config import PROCESSED_DIRS
from src.normalization.matches import transform_raw_matches

from . import config as cfg
from . import dedupe as dedup
from . import identity_new as ident_new


def load_existing_matches(tour: str) -> pd.DataFrame:
    return pd.read_parquet(PROCESSED_DIRS[tour.lower()] / "matches.parquet")


def integrate_incremental(tour: str, raw_incremental: pd.DataFrame, players: pd.DataFrame) -> dict:
    """`raw_incremental`: DataFrame no schema Sackmann bruto (colunas de
    `cfg.RAW_SCHEMA_COLUMNS`, MENOS winner_id/loser_id -- ainda nao
    resolvidos), com winner_name/loser_name preenchidos.

    Retorna {"combined": DataFrame (existente + novas, mesmo schema/ordenacao
    da Fase 2), "diagnostics": dict, "new_rows_transformed": DataFrame}.
    Quando `raw_incremental` esta vazio (caso real desta execucao -- ver
    docs/014), `combined` e exatamente `load_existing_matches(tour)`, sem
    nenhuma alteracao."""

    existing = load_existing_matches(tour)

    if raw_incremental.empty:
        diagnostics = {
            "tour": tour.upper(), "n_incoming_raw": 0, "n_duplicates_skipped": 0,
            "n_new_matches_incorporated": 0, "n_new_players": 0,
        }
        return {"combined": existing, "diagnostics": diagnostics, "new_rows_transformed": existing.iloc[0:0]}

    with_dup_flags = dedup.detect_duplicates(raw_incremental, existing, tour)
    non_duplicate = with_dup_flags[~with_dup_flags["is_duplicate"]].copy()

    if non_duplicate.empty:
        diagnostics = {
            "tour": tour.upper(),
            "n_incoming_raw": len(raw_incremental),
            "n_duplicates_skipped": int(with_dup_flags["is_duplicate"].sum()),
            "n_new_matches_incorporated": 0,
            "n_new_players": 0,
        }
        return {"combined": existing, "diagnostics": diagnostics, "new_rows_transformed": existing.iloc[0:0]}

    resolved = ident_new.resolve_incremental_players(non_duplicate, tour, players)
    n_new_players = int(
        (resolved["winner_resolution_method"] == "unresolved").sum()
        + (resolved["loser_resolution_method"] == "unresolved").sum()
    )

    transform_result = transform_raw_matches(resolved, tour)
    new_rows = transform_result["table"]

    combined = pd.concat([existing, new_rows], ignore_index=True)
    combined = combined.sort_values(
        ["tournament_date", "tourney_id", "match_id", "result"],
        ascending=[True, True, True, False],
    ).reset_index(drop=True)

    diagnostics = {
        "tour": tour.upper(),
        "n_incoming_raw": len(raw_incremental),
        "n_duplicates_skipped": int(with_dup_flags["is_duplicate"].sum()),
        "n_new_matches_incorporated": len(non_duplicate),
        "n_new_players": n_new_players,
        "transform_diagnostics": transform_result["diagnostics"],
    }
    return {"combined": combined, "diagnostics": diagnostics, "new_rows_transformed": new_rows}


def save_combined(tour: str, combined: pd.DataFrame) -> None:
    out_dir = cfg.INCREMENTAL_PROCESSED_DIR / tour.lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(out_dir / "matches.parquet", index=False)


def rebuild_features(combined: pd.DataFrame) -> pd.DataFrame:
    """Reaproveita EXATAMENTE o motor da Fase 3 (mesmas duas chamadas de
    `src.features.build.build_features_for_tour`) -- nunca reimplementado
    (item 6 da instrucao)."""

    profile = build_player_profile(combined)
    return build_matchup_table(profile)
