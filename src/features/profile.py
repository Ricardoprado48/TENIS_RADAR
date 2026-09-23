"""Perfil pre-jogo (point-in-time) de saque e devolucao por jogador-partida.

Junta: colunas derivadas (metrics.py) + janelas historicas (rolling.py) +
razoes numerador/denominador (metrics.ALL_METRICS) em um unico DataFrame
"player_serve_*" / "player_return_*", na mesma granularidade da tabela de
partidas da Fase 2 (1 linha por jogador por partida).

Este modulo NAO faz o self-join de matchup (isso e feito em matchup.py,
depois que o perfil de AMBOS os lados da partida ja existe).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import metrics as metrics_mod
from .config import (
    DEFAULT_DECAY_HALFLIFE_DAYS,
    LAST_N_WINDOWS,
    TIME_WINDOWS_DAYS,
)
from .rolling import compute_decay_priors, compute_windowed_priors

DECAY_SUFFIX = f"decay{DEFAULT_DECAY_HALFLIFE_DAYS}d"

# nomes de todas as janelas materializadas na base de saida (item 4 e 5 da
# instrucao da Fase 3)
ALL_WINDOW_NAMES = ["career"] + list(LAST_N_WINDOWS.keys()) + list(TIME_WINDOWS_DAYS.keys()) + [
    "surface_career", DECAY_SUFFIX,
]

CONTEXT_COLS = [
    "match_id", "tour", "tournament", "tourney_id", "tournament_date", "round",
    "surface", "tourney_level", "best_of", "player_id", "opponent_id",
    "player_name", "opponent_name", "player_rank", "opponent_rank", "result",
]


def _non_surface_windows() -> dict:
    windows = {"career": {"type": "all_prior"}}
    for name, n in LAST_N_WINDOWS.items():
        windows[name] = {"type": "last_n", "n": n}
    for name, days in TIME_WINDOWS_DAYS.items():
        windows[name] = {"type": "time", "days": days}
    return windows


def build_player_profile(table: pd.DataFrame) -> pd.DataFrame:
    """`table` e a tabela de partidas de UM tour (schema da Fase 2), ja
    ordenada cronologicamente como a Fase 2 grava (tournament_date,
    tourney_id, match_id, result). Retorna um DataFrame com as colunas de
    contexto + todas as features player_serve_*/player_return_* + colunas
    de qualidade de amostra (prior_matches_*, prior_service_points_*,
    prior_return_points_*) + flags de cold start."""

    df = metrics_mod.add_derived_columns(table)
    df = df.reset_index(drop=True)
    df["_seq"] = df.index

    value_cols = metrics_mod.base_value_columns()
    # cumsum/rolling sobre Int64 anulavel (pandas) tem suporte inconsistente
    # entre versoes; convertendo para float64 antes da agregacao evita isso.
    #
    # IMPORTANTE: apos converter, preenchemos NA->0 nas colunas de valor
    # (nao nas de saida!) antes de somar. Isso NAO e o "preenchimento com
    # zero" proibido pela Fase 2 -- e a forma padrao de implementar soma
    # ignorando ausencias (equivalente a sum(skipna=True)): Series.cumsum()
    # do pandas deixa NaN exatamente na posicao da linha ausente, o que
    # vazaria (via shift(1)) para a janela "anterior" da partida SEGUINTE,
    # zerando indevidamente o acumulado em vez de apenas pular aquela
    # partida. Tratando ausencia como contribuicao 0 na soma corrente, a
    # garantia de nao inventar dado se mantem no nivel que importa: a TAXA
    # final (numerador/denominador) so e computada quando o denominador
    # somado e > 0, e continua None quando nao ha nenhum dado real na
    # janela. Ver docs/007 secao 5.
    for c in value_cols:
        df[c] = df[c].astype("float64").fillna(0.0)

    # 1) janelas nao-surface (career, last10/20/50, last365d)
    priors = compute_windowed_priors(
        df, ["player_id"], "tournament_date", "_seq", value_cols, _non_surface_windows()
    )

    # 2) surface_career -- so entre partidas do jogador na MESMA superficie;
    # partidas com surface nulo ficam de fora do agrupamento e recebem NA/0.
    has_surface = df["surface"].notna()
    surface_priors_partial = compute_windowed_priors(
        df.loc[has_surface], ["player_id", "surface"], "tournament_date", "_seq",
        value_cols, {"surface_career": {"type": "all_prior"}},
    )
    surface_priors = surface_priors_partial.reindex(df.index)
    count_col = "n_prior_matches__surface_career"
    surface_priors[count_col] = surface_priors[count_col].fillna(0).astype("int64")

    # 3) janela ponderada por recencia (meia-vida configuravel, ver config.py)
    decay_priors = compute_decay_priors(
        df, ["player_id"], "tournament_date", "_seq", value_cols,
        float(DEFAULT_DECAY_HALFLIFE_DAYS), DECAY_SUFFIX,
    )

    priors_all = pd.concat([priors, surface_priors, decay_priors], axis=1)

    new_cols: dict[str, np.ndarray] = {}

    for window in ALL_WINDOW_NAMES:
        n_prior_col = f"n_prior_matches__{window}"
        if window == "surface_career":
            new_cols["surface_prior_matches"] = priors_all[n_prior_col].to_numpy()
            new_cols["surface_prior_service_points"] = priors_all[f"service_points__{window}"].to_numpy()
            new_cols["surface_prior_return_points"] = priors_all[f"return_points__{window}"].to_numpy()
        else:
            new_cols[f"prior_matches_{window}"] = priors_all[n_prior_col].to_numpy()
            new_cols[f"prior_service_points_{window}"] = priors_all[f"service_points__{window}"].to_numpy()
            new_cols[f"prior_return_points_{window}"] = priors_all[f"return_points__{window}"].to_numpy()

        for side, metric_dict in metrics_mod.ALL_METRICS.items():
            for metric_name, (num_col, den_col) in metric_dict.items():
                num = priors_all[f"{num_col}__{window}"].to_numpy(dtype="float64")
                den = priors_all[f"{den_col}__{window}"].to_numpy(dtype="float64")
                with np.errstate(divide="ignore", invalid="ignore"):
                    rate = np.where(den > 0, num / den, np.nan)
                new_cols[f"player_{side}_{metric_name}_{window}"] = rate

    new_cols["player_cold_start"] = (new_cols["prior_matches_career"] == 0)
    new_cols["player_surface_cold_start"] = (
        df["surface"].isna().to_numpy() | (new_cols["surface_prior_matches"] == 0)
    )

    out = pd.concat(
        [df[CONTEXT_COLS].reset_index(drop=True), pd.DataFrame(new_cols, index=df.index)],
        axis=1,
    )
    return out
