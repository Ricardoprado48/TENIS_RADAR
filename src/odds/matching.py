"""Casa uma entrada manual (bookmaker, tour, market, player, line) contra o
radar ja gerado pela Fase 8 (`precos_por_linha.parquet`) -- item 1/7/13.

Nunca inventa contexto: quando o jogador/linha nao e encontrado no radar
atual, a observacao bruta ainda e gravada (item 6, nunca perdida), mas a
comparacao fica marcada `matched=False` com o motivo exato, em vez de
inventar uma probabilidade operacional.
"""

from __future__ import annotations

import pandas as pd

from src.radar.identity import normalize_name


def _looks_like_player_id(value: str) -> bool:
    return isinstance(value, str) and "-" in value and value.split("-")[0] in ("ATP", "WTA")


def find_player_rows(prices: pd.DataFrame, tour: str, market: str, player: str) -> tuple[pd.DataFrame, str]:
    """Retorna (subconjunto de linhas candidatas, motivo se vazio)."""

    subset = prices[(prices["tour"] == tour) & (prices["market"] == market)]
    if subset.empty:
        return subset, f"nenhuma linha no radar atual para tour={tour} market={market}"

    if _looks_like_player_id(player):
        by_id = subset[subset["player_id"] == player]
        if not by_id.empty:
            return by_id, ""
        return by_id, f"player_id '{player}' nao encontrado no radar atual para {tour}/{market}"

    norm = normalize_name(player)
    by_name = subset[subset["player_name"] == norm]
    if by_name.empty:
        return by_name, f"jogador '{player}' (normalizado: '{norm}') nao encontrado no radar atual para {tour}/{market}"
    return by_name, ""


def match_line(player_rows: pd.DataFrame, line: float, side: str) -> tuple[pd.Series | None, str]:
    """item 14: linha da casa pode nao coincidir com a linha do modelo --
    nunca aproxima silenciosamente, so casa quando a linha (`.5`) existe
    exatamente na grade ja gerada pela Fase 8."""

    if player_rows.empty:
        return None, "jogador nao encontrado no radar atual"

    match_ids = player_rows["match_id"].unique()
    if len(match_ids) > 1:
        return None, f"jogador aparece em {len(match_ids)} partidas diferentes no radar atual -- ambiguo, nao escolhido automaticamente"

    exact = player_rows[(player_rows["line"] == float(line)) & (player_rows["side"] == side)]
    if exact.empty:
        available = sorted(player_rows["line"].unique().tolist())
        return None, (
            f"linha {line} ({side}) nao existe na grade do modelo para este jogador/mercado "
            f"-- linhas disponiveis: {available}"
        )
    if len(exact) > 1:
        return None, f"mais de uma linha {line}/{side} encontrada no radar atual (inesperado, nao escolhido automaticamente)"

    return exact.iloc[0], ""


def match_against_radar(tour: str, market: str, player: str, line: float, side: str, prices: pd.DataFrame) -> dict:
    """Ponto de entrada unico usado por `build.py`. Nunca lanca excecao por
    falta de match -- sempre retorna um dict com `matched` e, se False, o
    motivo exato (nunca associacao silenciosa, mesma regra da Fase 8)."""

    player_rows, reason = find_player_rows(prices, tour, market, player)
    if player_rows.empty:
        return {"matched": False, "match_reason": reason}

    row, reason = match_line(player_rows, line, side)
    if row is None:
        return {"matched": False, "match_reason": reason}

    return {
        "matched": True,
        "match_reason": "",
        "match_id": row["match_id"],
        "tournament": row["tournament"],
        "surface": row["surface_ctx"],
        "match_date": row["match_date"],
        "round": row["round"],
        "resolved_player_name": row["player_name"],
        "resolved_opponent_name": row["opponent_name"],
        "player_id": row["player_id"],
        "resolution_method_player": row["resolution_method_player"],
        "resolution_method_opponent": row["resolution_method_opponent"],
        "operational_probability": row["operational_probability"],
        "fair_odds": row["fair_odds"],
        "sample_bucket_career": row["sample_bucket_career"],
        "prior_matches_career": row["prior_matches_career"],
        "method_selected": row["method_selected"],
        "restricted": row["restricted"],
        "restricted_motivo": row["restricted_motivo"],
        "extreme_probability": row["extreme_probability"],
        "insufficient_history": row["insufficient_history"],
        "cold_start": row["cold_start"],
        "is_candidate": row["is_candidate"],
    }
