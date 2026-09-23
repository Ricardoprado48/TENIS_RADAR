"""Orquestra a Fase 2: le data/raw/, normaliza, valida e grava data/processed/.

Nunca escreve em data/raw/. Nao cria features, medias historicas, modelos ou
backtests -- isso e Fase 3+ (CLAUDE.md #22).
"""

import json

import pandas as pd

from .config import PROCESSED_DIRS, REPORTS_DIR, SAMPLES_DIR, TOURS
from .matches import build_player_match_table
from .players import load_players
from .rankings import load_rankings
from .reports import null_report, usable_matches_report
from .validate import check_ids, check_opponent_mirroring, check_two_rows_per_match


def run() -> dict:
    for d in list(PROCESSED_DIRS.values()) + [REPORTS_DIR, SAMPLES_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    all_diagnostics = {"matches": {}, "players": {}, "validation": {}}
    match_tables = {}

    for tour in TOURS:
        players_df, n_dup_players = load_players(tour)
        rankings_df = load_rankings(tour)
        result = build_player_match_table(tour)
        table = result["table"]
        match_tables[tour] = table

        players_df.to_parquet(PROCESSED_DIRS[tour] / "players.parquet", index=False)
        rankings_df.to_parquet(PROCESSED_DIRS[tour] / "rankings.parquet", index=False)
        table.to_parquet(PROCESSED_DIRS[tour] / "matches.parquet", index=False)

        all_diagnostics["matches"][tour] = result["diagnostics"]
        all_diagnostics["players"][tour] = {
            "n_players": len(players_df),
            "n_duplicate_player_ids": n_dup_players,
        }
        all_diagnostics["validation"][tour] = {
            "two_rows_per_match": check_two_rows_per_match(table),
            "opponent_mirroring": check_opponent_mirroring(table),
            "ids": check_ids(table),
        }

        sample = table[table["tour"] == tour.upper()].sort_values("tournament_date").tail(6)
        sample.to_csv(SAMPLES_DIR / f"matches_sample_{tour}.csv", index=False)

    combined = pd.concat(match_tables.values(), ignore_index=True)

    nulls = null_report(combined)
    nulls.to_csv(REPORTS_DIR / "null_report.csv", index=False)

    usable = usable_matches_report(combined)
    usable.to_csv(REPORTS_DIR / "usable_matches_report.csv", index=False)

    all_diagnostics["n_total_player_match_rows"] = len(combined)
    all_diagnostics["n_total_matches"] = combined["match_id"].nunique()

    with (REPORTS_DIR / "phase2_diagnostics.json").open("w", encoding="utf-8") as fh:
        json.dump(all_diagnostics, fh, indent=2, default=str, ensure_ascii=False)

    return {
        "diagnostics": all_diagnostics,
        "null_report": nulls,
        "usable_matches_report": usable,
    }


if __name__ == "__main__":
    out = run()
    print(json.dumps(out["diagnostics"], indent=2, default=str, ensure_ascii=False))
