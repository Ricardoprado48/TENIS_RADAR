"""Relatorios de qualidade pedidos explicitamente na Fase 2.

Nao calcula features nem metricas de projecao -- apenas mede o que existe
(ou falta) na base normalizada, para decidir quais mercados ja tem dado
suficiente para a Fase 3.
"""

import pandas as pd

NULL_REPORT_COLUMNS = [
    "player_rank", "opponent_rank", "player_rank_points", "opponent_rank_points",
    "aces", "double_faults", "service_points", "first_serves_in",
    "first_serve_points_won", "second_serve_points_won", "service_games",
    "break_points_saved", "break_points_faced",
    "opponent_aces", "opponent_double_faults", "return_points",
    "opponent_first_serves_in", "opponent_first_serve_points_won",
    "opponent_second_serve_points_won", "opponent_service_games",
    "break_points_created", "break_points_converted",
]


def null_report(table: pd.DataFrame) -> pd.DataFrame:
    """% de nulls por coluna, ano, tour e superficie (linhas jogador-partida)."""

    df = table.copy()
    df["year"] = df["tournament_date"].dt.year
    df["surface_grp"] = df["surface"].fillna("(sem surface)")

    records = []
    for (tour, year, surface), g in df.groupby(["tour", "year", "surface_grp"], dropna=False):
        n = len(g)
        for col in NULL_REPORT_COLUMNS:
            n_null = int(g[col].isna().sum())
            records.append({
                "tour": tour,
                "year": int(year) if pd.notna(year) else None,
                "surface": surface,
                "column": col,
                "n_rows": n,
                "n_null": n_null,
                "pct_null": round(n_null / n * 100, 2) if n else None,
            })
    return pd.DataFrame.from_records(records)


def usable_matches_report(table: pd.DataFrame) -> pd.DataFrame:
    """Quantidade de partidas (nao linhas) utilizaveis por mercado, por tour/ano.

    Uma partida e "utilizavel" para um mercado quando os campos brutos
    necessarios para calcula-lo na Fase 3 estao presentes para os DOIS
    jogadores. Nao calcula o valor do mercado em si (isso e Fase 3).
    """

    df = table.copy()
    df["year"] = df["tournament_date"].dt.year

    per_match = df.groupby(["tour", "match_id"], as_index=False).agg(
        year=("year", "first"),
        score=("score", "first"),
        aces_ok=("aces", lambda s: bool(s.notna().all())),
        df_ok=("double_faults", lambda s: bool(s.notna().all())),
        svgms_ok=("service_games", lambda s: bool(s.notna().all())),
        bp_saved_ok=("break_points_saved", lambda s: bool(s.notna().all())),
        bp_faced_ok=("break_points_faced", lambda s: bool(s.notna().all())),
    )
    per_match["holdbreak_ok"] = (
        per_match["svgms_ok"] & per_match["bp_saved_ok"] & per_match["bp_faced_ok"]
    )
    # total de games/sets se deriva do campo `score`; W/O = walkover, sem tenis jogado.
    per_match["score_present"] = per_match["score"].notna()
    per_match["is_walkover"] = per_match["score"].astype("string").str.contains("W/O", na=False)
    per_match["games_sets_ok"] = per_match["score_present"] & ~per_match["is_walkover"]

    summary = per_match.groupby(["tour", "year"], as_index=False).agg(
        n_matches=("match_id", "count"),
        usable_aces=("aces_ok", "sum"),
        usable_double_faults=("df_ok", "sum"),
        usable_total_games=("games_sets_ok", "sum"),
        usable_total_sets=("games_sets_ok", "sum"),
        usable_hold_break=("holdbreak_ok", "sum"),
    )

    total_row = {
        "tour": "TODOS", "year": None,
        "n_matches": int(summary["n_matches"].sum()),
        "usable_aces": int(summary["usable_aces"].sum()),
        "usable_double_faults": int(summary["usable_double_faults"].sum()),
        "usable_total_games": int(summary["usable_total_games"].sum()),
        "usable_total_sets": int(summary["usable_total_sets"].sum()),
        "usable_hold_break": int(summary["usable_hold_break"].sum()),
    }
    summary = pd.concat([summary, pd.DataFrame([total_row])], ignore_index=True)
    return summary
