"""Aplica o modelo analitico de games/sets/tie-break (setmodel.py) linha a
linha, nas janelas headline (career, surface_career, last50 -- as unicas
com colunas `opponent_*`/self-join disponiveis, ver docs/007 secao 8),
comparando explicitamente (item 3 da instrucao):

  isolated: p_hold_A = player_serve_hold_pct_w (proprio),
            p_hold_B = opponent_serve_hold_pct_w (do adversario, mas SEM
            considerar quem ele esta devolvendo -- so o hold% cru dele)
  matchup:  p_hold_A = media(player_serve_hold_pct_w,
                              1 - opponent_return_break_pct_w)
            p_hold_B = media(opponent_serve_hold_pct_w,
                              1 - player_return_break_pct_w)
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from src.features.config import HEADLINE_WINDOWS

from .setmodel import match_expectation

# janelas onde a Fase 3 materializou opponent_adjusted_hold_pct/break_pct
# (ver src/features/matchup.py _ADJUSTMENT_WINDOWS)
_ADJUSTMENT_WINDOWS = ["career", "last50"]


def _p_hold_pair(df: pd.DataFrame, window: str, variant: str):
    own_hold = df[f"player_serve_hold_pct_{window}"].to_numpy(dtype="float64")
    opp_hold = df[f"opponent_serve_hold_pct_{window}"].to_numpy(dtype="float64")
    if variant == "isolated":
        return own_hold, opp_hold
    opp_break_faced_by_player = df[f"opponent_return_break_pct_{window}"].to_numpy(dtype="float64")
    player_break_vs_opp = df[f"player_return_break_pct_{window}"].to_numpy(dtype="float64")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        p_a = np.nanmean(np.vstack([own_hold, 1.0 - opp_break_faced_by_player]), axis=0)
        p_b = np.nanmean(np.vstack([opp_hold, 1.0 - player_break_vs_opp]), axis=0)
    if variant == "matchup":
        return p_a, p_b
    # "oppadj": parte do matchup e soma o residuo de ajuste por forca media
    # do adversario (Fase 3 item 9) -- mesma composicao (matchup + residuo)
    # usada em rate_models.py para aces (ver docs/008 secao 3). So temos os
    # residuos DO PROPRIO jogador da linha (nao os do adversario, que
    # exigiriam outro self-join): `opponent_adjusted_hold_pct` (quanto ESTE
    # jogador segura o saque acima/abaixo do esperado dado quem enfrentou) e
    # `opponent_adjusted_break_pct` (quanto ESTE jogador quebra o saque do
    # adversario acima/abaixo do esperado). O 2o desconta de p_b (break a
    # mais do jogador reduz o hold esperado do adversario).
    hold_resid = df[f"opponent_adjusted_hold_pct_{window}"].to_numpy(dtype="float64")
    break_resid = df[f"opponent_adjusted_break_pct_{window}"].to_numpy(dtype="float64")
    p_a = p_a + hold_resid
    p_b = p_b - break_resid
    return p_a, p_b


def add_games_predictions(df: pd.DataFrame) -> pd.DataFrame:
    best_of = df["best_of"].to_numpy()
    out = {}
    for w in HEADLINE_WINDOWS:
        variants = ["isolated", "matchup"] + (["oppadj"] if w in _ADJUSTMENT_WINDOWS else [])
        for variant in variants:
            p_a, p_b = _p_hold_pair(df, w, variant)
            e_games = np.full(len(df), np.nan)
            e_diff = np.full(len(df), np.nan)
            e_n_sets = np.full(len(df), np.nan)
            p_tb = np.full(len(df), np.nan)
            p_full_distance = np.full(len(df), np.nan)
            for i in range(len(df)):
                pa, pb, bo = p_a[i], p_b[i], best_of[i]
                if not (np.isfinite(pa) and np.isfinite(pb)) or pd.isna(bo):
                    continue
                bo_int = int(bo)
                res = match_expectation(float(pa), float(pb), bo_int)
                e_games[i] = res["e_total_games"]
                e_diff[i] = res["e_game_diff"]
                e_n_sets[i] = res["e_n_sets"]
                p_tb[i] = res["p_tiebreak_match"]
                p_full_distance[i] = res["p_sets_count"].get(bo_int, np.nan)
            out[f"pred_total_games_{variant}_{w}"] = e_games
            out[f"pred_game_diff_{variant}_{w}"] = e_diff
            out[f"pred_n_sets_{variant}_{w}"] = e_n_sets
            out[f"pred_p_tiebreak_{variant}_{w}"] = p_tb
            out[f"pred_p_full_distance_{variant}_{w}"] = p_full_distance
    return pd.concat([df, pd.DataFrame(out, index=df.index)], axis=1)
