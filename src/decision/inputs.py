"""Enriquecimento das comparacoes da Fase 9 com contexto adicional, sem
recalcular nenhuma probabilidade/odd/edge -- so junta colunas ja existentes
(ou re-derivadas pelo MESMO motor ja testado, nunca reimplementado) que a
tabela `comparison_with_model.parquet` da Fase 9 nao carrega:

  - identidade (`player_id`, metodo de resolucao dos dois lados, superficie)
    -- via join com `data/outputs/phase8/precos_por_linha.parquet`, pela
    mesma chave normalizada de nome que `src.odds.matching` ja usa;
  - contadores de amostra (`prior_service_points_career`,
    `prior_return_points_career`, `surface_prior_matches`) -- via
    `src.radar.features_future.build_future_feature_rows`, reaplicado
    sobre `data/outputs/phase8/partidas_resolvidas.parquet` (o MESMO motor
    point-in-time da Fase 3/8, chamado aqui so para expor colunas que a
    Fase 8 nao propagou ate `precos_por_linha.parquet` -- nenhum modelo e
    retreinado, nenhuma feature e alterada)."""

from __future__ import annotations

import pandas as pd

from src.radar import config as radar_cfg
from src.radar import features_future as feat
from src.radar.identity import normalize_name

from . import config as cfg

_PRICE_CONTEXT_COLS = [
    "tour", "market", "match_id", "line", "side", "player_name",
    "player_id", "surface_ctx", "method_selected", "cold_start",
    "insufficient_history", "calibrator_insufficient_sample",
    "resolution_method_player", "resolution_method_opponent",
]


def load_radar_prices() -> pd.DataFrame:
    return pd.read_parquet(cfg.PHASE8_PRICES_PATH)


def load_resolved_matches() -> pd.DataFrame:
    return pd.read_parquet(cfg.PHASE8_RESOLVED_PATH)


def build_sample_feature_table(resolved: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por (match_id, player_id) com os contadores de amostra
    (item 5) para partidas futuras -- reaproveita
    `src.radar.features_future.build_future_feature_rows` (Fase 3/8), nunca
    reimplementado. Retorna DataFrame vazio se nao houver partida usavel."""

    parts = []
    for tour in radar_cfg.TOURS:
        resolved_tour = resolved[resolved["tour"] == tour]
        rows = feat.build_future_feature_rows(tour, resolved_tour)
        if rows.empty:
            continue
        parts.append(rows[[
            "match_id", "player_id", "prior_matches_career",
            "prior_service_points_career", "prior_return_points_career",
            "surface_prior_matches", "player_cold_start",
            "player_surface_cold_start",
        ]])
    if not parts:
        return pd.DataFrame(columns=[
            "match_id", "player_id", "prior_matches_career",
            "prior_service_points_career", "prior_return_points_career",
            "surface_prior_matches", "player_cold_start",
            "player_surface_cold_start",
        ])
    return pd.concat(parts, ignore_index=True)


def enrich_comparisons(comparisons: pd.DataFrame, prices: pd.DataFrame, resolved: pd.DataFrame) -> pd.DataFrame:
    """Junta `comparison_with_model.parquet` (Fase 9) com contexto de
    identidade (Fase 8) e contadores de amostra (Fase 3/8, re-derivados).
    Linhas nao casadas na Fase 9 (`matched=False`) continuam presentes,
    apenas sem o contexto adicional (colunas ficam NaN/None) -- nunca
    descartadas (mesma regra da Fase 9: observacao bruta nunca perdida)."""

    if comparisons.empty:
        return comparisons

    out = comparisons.copy()
    out["_player_norm"] = out["player"].map(normalize_name)

    price_ctx = prices[_PRICE_CONTEXT_COLS].copy()
    price_ctx["_player_norm"] = price_ctx["player_name"]

    out = out.merge(
        price_ctx.drop(columns=["player_name"]),
        on=["tour", "market", "match_id", "line", "side", "_player_norm"],
        how="left",
    )

    sample_feats = build_sample_feature_table(resolved)
    out = out.merge(sample_feats, on=["match_id", "player_id"], how="left")

    out = out.drop(columns=["_player_norm"])
    return out
