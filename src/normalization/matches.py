"""Normalizacao das partidas: formato longo (1 linha por jogador por partida).

Cada partida bruta do Sackmann ja contem, na mesma linha, as estatisticas de
saque de AMBOS os jogadores (prefixo w_ para o vencedor, l_ para o
perdedor). Isso significa que as "estatisticas de devolucao" pedidas para a
Fase 2 (opponent_aces, return_points, break_points_created, ...) nao exigem
nenhum lookup entre partidas: sao exatamente as estatisticas de saque do
adversario naquela mesma partida, apenas espelhadas para a perspectiva do
devolvedor. Ver CLAUDE.md #2 (regra do matchup) e #6.

Regra de nao preenchimento com zero (pedido explicito da Fase 2): todas as
colunas numericas usam dtype nullable (Int64) e a ausencia no CSV bruto
(string vazia) vira <NA>, nunca 0. Subtracoes (break_points_converted)
propagam <NA> automaticamente quando um dos operandos e nulo.
"""

import pandas as pd

from .config import MATCH_FILES, RAW_DIRS
from .players import canonical_player_id

# colunas que devem ser inteiros anulaveis no output (nunca 0 para "ausente")
INT_COLUMNS = [
    "best_of", "minutes",
    "player_rank", "opponent_rank", "player_rank_points", "opponent_rank_points",
    "aces", "double_faults", "service_points", "first_serves_in",
    "first_serve_points_won", "second_serve_points_won", "service_games",
    "break_points_saved", "break_points_faced",
    "opponent_aces", "opponent_double_faults", "return_points",
    "opponent_first_serves_in", "opponent_first_serve_points_won",
    "opponent_second_serve_points_won", "opponent_service_games",
    "break_points_created", "break_points_converted",
]

OUTPUT_COLUMNS = [
    # contexto
    "match_id", "tour", "tournament", "tourney_id", "tournament_date", "round",
    "surface", "tourney_level", "best_of", "minutes", "score",
    "player_id", "opponent_id", "player_name", "opponent_name",
    "player_hand", "opponent_hand",
    "player_rank", "opponent_rank", "player_rank_points", "opponent_rank_points",
    "result",
    # saque do jogador
    "aces", "double_faults", "service_points", "first_serves_in",
    "first_serve_points_won", "second_serve_points_won", "service_games",
    "break_points_saved", "break_points_faced",
    # devolucao do jogador (= saque do adversario espelhado)
    "opponent_aces", "opponent_double_faults", "return_points",
    "opponent_first_serves_in", "opponent_first_serve_points_won",
    "opponent_second_serve_points_won", "opponent_service_games",
    "break_points_created", "break_points_converted",
]


def _load_raw_matches(tour: str) -> pd.DataFrame:
    raw_dir = RAW_DIRS[tour]
    frames = []
    for file_name in MATCH_FILES[tour]:
        df = pd.read_csv(raw_dir / file_name)
        df["_source_file"] = file_name
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def _preprocess(df: pd.DataFrame, tour: str) -> pd.DataFrame:
    df = df.copy()
    df["tournament_date"] = pd.to_datetime(df["tourney_date"], format="%Y%m%d", errors="coerce")
    df["match_id"] = (
        tour.upper() + ":" + df["tourney_id"].astype(str) + ":" + df["match_num"].astype(str)
    )
    df["surface"] = df["surface"].astype("string").str.strip().str.title().replace({"": pd.NA})
    df["round"] = df["round"].astype("string").str.strip()
    return df


def _build_perspective(df: pd.DataFrame, tour: str, is_winner: bool) -> pd.DataFrame:
    own_prefix, opp_prefix = ("w_", "l_") if is_winner else ("l_", "w_")
    own_role, opp_role = ("winner", "loser") if is_winner else ("loser", "winner")

    out = pd.DataFrame(index=df.index)
    out["match_id"] = df["match_id"]
    out["tour"] = tour.upper()
    out["tournament"] = df["tourney_name"]
    out["tourney_id"] = df["tourney_id"]
    out["tournament_date"] = df["tournament_date"]
    out["round"] = df["round"]
    out["surface"] = df["surface"]
    out["tourney_level"] = df["tourney_level"]
    out["best_of"] = df["best_of"]
    out["minutes"] = df["minutes"]
    out["score"] = df["score"]

    out["player_id"] = [canonical_player_id(tour, pid) for pid in df[f"{own_role}_id"]]
    out["opponent_id"] = [canonical_player_id(tour, pid) for pid in df[f"{opp_role}_id"]]
    out["player_name"] = df[f"{own_role}_name"]
    out["opponent_name"] = df[f"{opp_role}_name"]
    out["player_hand"] = df[f"{own_role}_hand"]
    out["opponent_hand"] = df[f"{opp_role}_hand"]
    out["player_rank"] = df[f"{own_role}_rank"]
    out["opponent_rank"] = df[f"{opp_role}_rank"]
    out["player_rank_points"] = df[f"{own_role}_rank_points"]
    out["opponent_rank_points"] = df[f"{opp_role}_rank_points"]
    out["result"] = "W" if is_winner else "L"

    # saque do proprio jogador
    out["aces"] = df[f"{own_prefix}ace"]
    out["double_faults"] = df[f"{own_prefix}df"]
    out["service_points"] = df[f"{own_prefix}svpt"]
    out["first_serves_in"] = df[f"{own_prefix}1stIn"]
    out["first_serve_points_won"] = df[f"{own_prefix}1stWon"]
    out["second_serve_points_won"] = df[f"{own_prefix}2ndWon"]
    out["service_games"] = df[f"{own_prefix}SvGms"]
    out["break_points_saved"] = df[f"{own_prefix}bpSaved"]
    out["break_points_faced"] = df[f"{own_prefix}bpFaced"]

    # oportunidades de devolucao do jogador = saque do adversario espelhado
    out["opponent_aces"] = df[f"{opp_prefix}ace"]
    out["opponent_double_faults"] = df[f"{opp_prefix}df"]
    out["return_points"] = df[f"{opp_prefix}svpt"]
    out["opponent_first_serves_in"] = df[f"{opp_prefix}1stIn"]
    out["opponent_first_serve_points_won"] = df[f"{opp_prefix}1stWon"]
    out["opponent_second_serve_points_won"] = df[f"{opp_prefix}2ndWon"]
    out["opponent_service_games"] = df[f"{opp_prefix}SvGms"]
    out["break_points_created"] = df[f"{opp_prefix}bpFaced"]
    out["break_points_converted"] = df[f"{opp_prefix}bpFaced"] - df[f"{opp_prefix}bpSaved"]

    return out


def transform_raw_matches(raw: pd.DataFrame, tour: str) -> dict:
    """Aplica exatamente as regras de transformacao da Fase 2 (perspectiva
    dupla winner/loser, dtypes, ordenacao de colunas) a um DataFrame bruto
    no schema Sackmann (winner_id/loser_id, w_*/l_* de saque, tourney_id,
    tourney_date, match_num, ...), SEM ordenar por data nem exigir que os
    dados venham de `data/raw/sackmann_*`.

    Extraida de `build_player_match_table` para ser reaproveitada tambem
    pela Fase 8.1 (atualizacao incremental) -- mesma funcao, nunca um
    segundo schema (ver CLAUDE.md #11 e item 5 da Fase 8.1)."""

    missing_ids_mask = raw["winner_id"].isna() | raw["loser_id"].isna()
    n_missing_ids = int(missing_ids_mask.sum())
    raw = raw.loc[~missing_ids_mask].copy()

    raw = _preprocess(raw, tour)

    dup_match_id_mask = raw.duplicated(subset=["match_id"], keep=False)
    n_duplicate_match_ids = int(dup_match_id_mask.sum())

    winner_rows = _build_perspective(raw, tour, is_winner=True)
    loser_rows = _build_perspective(raw, tour, is_winner=False)
    table = pd.concat([winner_rows, loser_rows], ignore_index=True)

    for col in INT_COLUMNS:
        table[col] = pd.array(pd.to_numeric(table[col], errors="coerce"), dtype="Int64")

    for col in ["match_id", "tour", "tournament", "tourney_id", "round", "surface",
                "tourney_level", "score", "player_id", "opponent_id", "player_name",
                "opponent_name", "player_hand", "opponent_hand", "result"]:
        table[col] = table[col].astype("string")

    table = table[OUTPUT_COLUMNS]

    diagnostics = {
        "n_matches_missing_player_id": n_missing_ids,
        "n_matches_used": len(raw),
        "n_player_match_rows": len(table),
        "expected_rows": len(raw) * 2,
        "rows_match_expected": len(table) == len(raw) * 2,
        "n_duplicate_match_ids": n_duplicate_match_ids,
    }

    return {"table": table, "diagnostics": diagnostics}


def build_player_match_table(tour: str) -> dict:
    """Retorna {"table": DataFrame, "diagnostics": dict} para um tour."""

    raw = _load_raw_matches(tour)
    n_raw_matches = len(raw)

    result = transform_raw_matches(raw, tour)
    table = result["table"].sort_values(
        ["tournament_date", "tourney_id", "match_id", "result"],
        ascending=[True, True, True, False],  # "W" antes de "L" dentro da mesma partida
    ).reset_index(drop=True)

    diagnostics = {"tour": tour.upper(), "n_raw_matches": n_raw_matches, **result["diagnostics"]}

    return {"table": table, "diagnostics": diagnostics}
