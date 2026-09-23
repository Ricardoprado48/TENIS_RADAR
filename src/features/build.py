"""Orquestrador da Fase 3: monta a tabela final de features point-in-time
por tour e grava em data/processed/features/.

Pipeline por tour:
  1. ler data/processed/{tour}/matches.parquet (Fase 2, NUNCA reescrito aqui)
  2. parser de score (item 1) -- anexado como colunas de contexto por partida
  3. perfil point-in-time do jogador (profile.py, itens 2-7)
  4. matchup (self-join do adversario + comparativos + ajuste, itens 8-9)
  5. gravar Parquet em data/processed/features/{tour}/player_match_features.parquet
"""

from __future__ import annotations

import pandas as pd

from src.normalization.config import PROCESSED_DIRS, TOURS

from .config import FEATURES_REPORTS_DIR, FEATURES_SAMPLES_DIR, FEATURES_TOUR_DIRS
from .matchup import build_matchup_table
from .profile import build_player_profile
from .reports import matchup_coverage_report, sample_size_report, score_coverage_report
from .score_parser import parse_score_column


def build_features_for_tour(tour: str) -> dict:
    matches_path = PROCESSED_DIRS[tour] / "matches.parquet"
    matches = pd.read_parquet(matches_path)
    matches = matches.sort_values(
        ["tournament_date", "tourney_id", "match_id", "result"],
        ascending=[True, True, True, False],
    ).reset_index(drop=True)

    profile = build_player_profile(matches)
    full = build_matchup_table(profile)

    score_cols = parse_score_column(matches["score"])
    full = pd.concat([full.reset_index(drop=True), score_cols.reset_index(drop=True)], axis=1)

    diagnostics = {
        "tour": tour.upper(),
        "n_rows": len(full),
        "n_matches": full["match_id"].nunique(),
        "n_cold_start_rows": int(full["player_cold_start"].sum()),
        "n_columns": len(full.columns),
        "score_status_counts": full["score_status"].value_counts(dropna=False).to_dict(),
        "score_complete_pct": float(full["score_complete"].mean()),
    }
    return {"table": full, "diagnostics": diagnostics}


def run() -> dict:
    FEATURES_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    FEATURES_SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    all_diagnostics = {}
    sample_reports = []
    score_reports = []
    matchup_reports = {}
    tables = {}
    for tour in TOURS:
        result = build_features_for_tour(tour)
        table = result["table"]
        tables[tour] = table
        out_dir = FEATURES_TOUR_DIRS[tour]
        out_dir.mkdir(parents=True, exist_ok=True)
        table.to_parquet(out_dir / "player_match_features.parquet", index=False)
        all_diagnostics[tour] = result["diagnostics"]

        ssr = sample_size_report(table)
        ssr.insert(0, "tour", tour.upper())
        sample_reports.append(ssr)

        scr = score_coverage_report(table)
        scr.insert(0, "tour", tour.upper())
        score_reports.append(scr)

        matchup_reports[tour.upper()] = matchup_coverage_report(table)

        table.head(6).to_csv(FEATURES_SAMPLES_DIR / f"features_sample_{tour}.csv", index=False)

    pd.concat(sample_reports, ignore_index=True).to_csv(FEATURES_REPORTS_DIR / "sample_size_report.csv", index=False)
    pd.concat(score_reports, ignore_index=True).to_csv(FEATURES_REPORTS_DIR / "score_coverage_report.csv", index=False)

    all_diagnostics["matchup_coverage"] = matchup_reports

    import json
    (FEATURES_REPORTS_DIR / "phase3_diagnostics.json").write_text(
        json.dumps(all_diagnostics, indent=2, default=str), encoding="utf-8"
    )
    return all_diagnostics


if __name__ == "__main__":
    import json

    print(json.dumps(run(), indent=2, default=str))
