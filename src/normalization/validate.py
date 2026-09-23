"""Validacoes de transformacao pedidas explicitamente na Fase 2.

Confere, sobre os dados ja normalizados (nao recalcula nada), que:
  1. cada partida valida gerou exatamente duas linhas;
  2. as estatisticas do adversario foram espelhadas corretamente;
  3. nao ha player_id/opponent_id/match_id ausentes ou match_id duplicado.
"""

import pandas as pd

# (campo do proprio jogador, campo espelhado do adversario) -- devem ser
# iguais entre a linha do vencedor e a linha do perdedor da mesma partida.
MIRROR_PAIRS = [
    ("aces", "opponent_aces"),
    ("double_faults", "opponent_double_faults"),
    ("service_points", "return_points"),
    ("first_serves_in", "opponent_first_serves_in"),
    ("first_serve_points_won", "opponent_first_serve_points_won"),
    ("second_serve_points_won", "opponent_second_serve_points_won"),
    ("service_games", "opponent_service_games"),
    ("break_points_faced", "break_points_created"),
]


def _eq_or_both_null(a: pd.Series, b: pd.Series) -> pd.Series:
    a_num = pd.to_numeric(a, errors="coerce")
    b_num = pd.to_numeric(b, errors="coerce")
    return (a_num == b_num) | (a_num.isna() & b_num.isna())


def check_two_rows_per_match(table: pd.DataFrame) -> dict:
    counts = table.groupby("match_id").size()
    bad = counts[counts != 2]
    return {
        "n_matches": int(counts.shape[0]),
        "n_matches_with_exactly_two_rows": int((counts == 2).sum()),
        "n_matches_with_wrong_row_count": int(bad.shape[0]),
        "example_bad_match_ids": bad.index[:10].tolist(),
    }


def check_opponent_mirroring(table: pd.DataFrame) -> dict:
    w = table[table["result"] == "W"].set_index("match_id")
    l = table[table["result"] == "L"].set_index("match_id")
    common = w.index.intersection(l.index)
    w, l = w.loc[common], l.loc[common]

    results = {}
    total_mismatches = 0
    for own_field, opp_field in MIRROR_PAIRS:
        ok_w = _eq_or_both_null(w[own_field], l[opp_field])
        ok_l = _eq_or_both_null(l[own_field], w[opp_field])
        n_bad = int((~ok_w).sum() + (~ok_l).sum())
        results[f"{own_field}<->{opp_field}"] = n_bad
        total_mismatches += n_bad

    return {
        "n_match_pairs_checked": int(len(common)),
        "n_field_mismatches_total": total_mismatches,
        "mismatches_by_field_pair": results,
    }


def check_ids(table: pd.DataFrame) -> dict:
    n_missing_player_id = int(table["player_id"].isna().sum())
    n_missing_opponent_id = int(table["opponent_id"].isna().sum())
    n_missing_match_id = int(table["match_id"].isna().sum())

    dup_counts = table.groupby("match_id")["result"].apply(lambda s: (s == "W").sum())
    n_match_ids_with_more_than_one_winner_row = int((dup_counts > 1).sum())

    return {
        "n_missing_player_id": n_missing_player_id,
        "n_missing_opponent_id": n_missing_opponent_id,
        "n_missing_match_id": n_missing_match_id,
        "n_match_ids_with_more_than_one_winner_row": n_match_ids_with_more_than_one_winner_row,
    }
