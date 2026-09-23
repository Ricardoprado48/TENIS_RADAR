"""Relatorios de cobertura da Fase 3 (item 7 e item 13 da instrucao)."""

from __future__ import annotations

import pandas as pd

SAMPLE_SIZE_THRESHOLDS = [1, 10, 20, 50]


def sample_size_report(table: pd.DataFrame) -> pd.DataFrame:
    """Para cada janela, qual fracao das linhas ja tem >= N partidas
    anteriores disponiveis (cold start vs. amostra pequena vs. robusta)."""

    prior_cols = [c for c in table.columns if c.startswith("prior_matches_")] + ["surface_prior_matches"]
    rows = []
    n = len(table)
    for col in prior_cols:
        window = col.replace("prior_matches_", "") if col != "surface_prior_matches" else "surface_career"
        for threshold in SAMPLE_SIZE_THRESHOLDS:
            pct = float((table[col] >= threshold).mean())
            rows.append({"window": window, "min_prior_matches": threshold, "pct_rows": pct, "n_rows": n})
    return pd.DataFrame(rows)


def score_coverage_report(table: pd.DataFrame) -> pd.DataFrame:
    grp = table.groupby("score_status", dropna=False).agg(
        n_rows=("match_id", "count"),
        n_complete=("score_complete", "sum"),
    ).reset_index()
    grp["pct_of_total"] = grp["n_rows"] / len(table)
    return grp


def matchup_coverage_report(table: pd.DataFrame) -> dict:
    """Quantas linhas tem o outro lado do confronto (opponent_*) disponivel
    -- so falta quando o adversario e ele mesmo cold start naquela janela."""

    out = {}
    for w in ["career", "surface_career", "last50"]:
        col = f"opponent_serve_ace_rate_{w}"
        if col in table.columns:
            out[w] = {
                "pct_with_opponent_data": float(table[col].notna().mean()),
                "n_rows": len(table),
            }
    return out
