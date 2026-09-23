"""Rotulos (y_true) para avaliacao da Fase 4.

Quase todos os alvos ja existem na tabela de features da Fase 3, derivados
do parser de score (score_total_games, score_game_diff, score_n_sets_completed,
score_has_tiebreak) -- so precisam ser reorientados da perspectiva
"vencedor/perdedor" (como o parser reporta, porque o placar bruto sempre
lista o vencedor da PARTIDA primeiro) para a perspectiva "player/opponent"
de cada linha, usando a coluna `result` (W/L) que ja esta na tabela.

As DUAS excecoes sao aces e double faults DA PROPRIA PARTIDA: a Fase 3
deliberadamente NAO inclui essas colunas na base de features (elas
descreveriam a propria partida sendo avaliada, e entrariam em conflito com
o desenho point-in-time se fossem confundidas com feature). Para poder
avaliar "quantos aces o modelo previu vs quantos realmente aconteceram",
essas 2 colunas (`aces`, `double_faults`) sao lidas do parquet imutavel da
Fase 2 (data/processed/{tour}/matches.parquet) e usadas SOMENTE como rotulo
de avaliacao -- nunca como entrada de nenhum modelo. `opponent_aces` (Fase 2)
tambem e lida para derivar o total de aces da partida.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.normalization.config import PROCESSED_DIRS


def attach_targets(features: pd.DataFrame, tour: str) -> pd.DataFrame:
    """Recebe a tabela de features da Fase 3 de UM tour e retorna a mesma
    tabela com colunas `target_*` anexadas (nunca usadas como preditor)."""

    df = features.copy()

    is_winner = df["result"] == "W"

    # --- derivados do parser de score (ja point-in-time-safe: sao o
    # RESULTADO da propria partida, usado so como rotulo, nao como feature) ---
    df["target_total_games"] = df["score_total_games"]
    df["target_total_sets"] = df["score_n_sets_completed"]
    df["target_has_tiebreak"] = df["score_has_tiebreak"]
    # score_game_diff = winner_games - loser_games (perspectiva do parser).
    # Reorientado para "games do player - games do opponent".
    df["target_game_diff"] = np.where(
        is_winner, df["score_game_diff"],
        -df["score_game_diff"].astype("Float64"),
    )
    df["target_score_complete"] = df["score_complete"]

    # --- unica leitura da Fase 2: aces/double_faults da PROPRIA partida ---
    raw = pd.read_parquet(
        PROCESSED_DIRS[tour] / "matches.parquet",
        columns=["match_id", "player_id", "aces", "double_faults", "opponent_aces"],
    )
    raw = raw.rename(columns={
        "aces": "target_aces", "double_faults": "target_double_faults",
        "opponent_aces": "_opp_aces_for_total",
    })
    df = df.merge(raw, on=["match_id", "player_id"], how="left", validate="one_to_one")
    df["target_total_aces_match"] = df["target_aces"] + df["_opp_aces_for_total"]
    df = df.drop(columns=["_opp_aces_for_total"])

    return df
