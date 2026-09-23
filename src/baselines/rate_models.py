"""Baselines por taxa (Ace Rate, Double Fault Rate) -- item 2/3 da instrucao,
incluindo a comparacao explicita "jogador isolado vs Serve x Return" (item
3): para cada janela, um modelo A usa so a taxa do proprio jogador, um
modelo B combina com a taxa do adversario (ja trazida pelo self-join da
Fase 3, `opponent_*`, disponivel so nas janelas headline -- career,
surface_career, last50 -- porque foi assim que a Fase 3 conteve a explosao
de colunas; ver docs/007 secao 8).

Contagem prevista = taxa prevista * volume de pontos de saque esperado
naquela janela (prior_service_points_{w} / prior_matches_{w}, ja calculado
na Fase 3 -- nao reinventado aqui).
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from src.features.config import HEADLINE_WINDOWS
from src.features.profile import ALL_WINDOW_NAMES

# janelas onde a Fase 3 materializou opponent_adjusted_* (item 9 da Fase 3 /
# item 8 da Fase 4 -- ver src/features/matchup.py _ADJUSTMENT_WINDOWS)
_ADJUSTMENT_WINDOWS = ["career", "last50"]


def _svc_pts_per_match(df: pd.DataFrame, window: str) -> np.ndarray:
    if window == "surface_career":
        num = df["surface_prior_service_points"].to_numpy(dtype="float64")
        den = df["surface_prior_matches"].to_numpy(dtype="float64")
    else:
        num = df[f"prior_service_points_{window}"].to_numpy(dtype="float64")
        den = df[f"prior_matches_{window}"].to_numpy(dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / den, np.nan)


def add_ace_predictions(df: pd.DataFrame) -> pd.DataFrame:
    out = {}
    for w in ALL_WINDOW_NAMES:
        svc = _svc_pts_per_match(df, w)
        rate_iso = df[f"player_serve_ace_rate_{w}"].to_numpy(dtype="float64")
        out[f"pred_aces_isolated_{w}"] = rate_iso * svc
        if w in HEADLINE_WINDOWS:
            opp_col = f"opponent_return_ace_allowed_rate_{w}"
            if opp_col in df.columns:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=RuntimeWarning)
                    rate_mu = np.nanmean(
                        np.vstack([rate_iso, df[opp_col].to_numpy(dtype="float64")]), axis=0,
                    )
                out[f"pred_aces_matchup_{w}"] = rate_mu * svc
        if w in _ADJUSTMENT_WINDOWS:
            # item 8/9 (Fase 4 item 8 = comparar com/sem opponent adjustment):
            # parte da previsao matchup (que ja usa o Ace Allowed Rate DESTE
            # adversario especifico) e soma o residuo de ajuste por forca
            # media do adversario do proprio jogador (Fase 3 item 9) -- uma
            # composicao simples e nao circular (ver docs/008 secao 3).
            adj_col = f"opponent_adjusted_ace_rate_{w}"
            matchup_key = f"pred_aces_matchup_{w}"
            if adj_col in df.columns and matchup_key in out:
                adj_rate = df[adj_col].to_numpy(dtype="float64")
                out[f"pred_aces_oppadj_{w}"] = out[matchup_key] + adj_rate * svc
    return pd.concat([df, pd.DataFrame(out, index=df.index)], axis=1)


def add_double_fault_predictions(df: pd.DataFrame) -> pd.DataFrame:
    out = {}
    for w in ALL_WINDOW_NAMES:
        svc = _svc_pts_per_match(df, w)
        rate = df[f"player_serve_double_fault_rate_{w}"].to_numpy(dtype="float64")
        out[f"pred_double_faults_{w}"] = rate * svc
    return pd.concat([df, pd.DataFrame(out, index=df.index)], axis=1)


def add_total_aces_predictions(df: pd.DataFrame) -> pd.DataFrame:
    """Soma das previsoes individuais (item 2, "Total de aces"): self-join
    para trazer a previsao `pred_aces_*` que a linha do ADVERSARIO ja tem
    (calculada a partir do historico dele proprio), e soma com a previsao
    da propria linha."""

    pred_cols = [
        c for c in df.columns
        if c.startswith("pred_aces_isolated_") or c.startswith("pred_aces_matchup_") or c.startswith("pred_aces_oppadj_")
    ]
    right = df[["match_id", "player_id"] + pred_cols].rename(
        columns={"player_id": "_opp_player_id", **{c: f"_opp_{c}" for c in pred_cols}}
    )
    merged = df.merge(right, left_on=["match_id", "opponent_id"], right_on=["match_id", "_opp_player_id"], how="left")
    merged = merged.drop(columns=["_opp_player_id"])

    out = {}
    for c in pred_cols:
        total_name = "pred_total_aces_" + c[len("pred_aces_"):]
        out[total_name] = merged[c].to_numpy(dtype="float64") + merged[f"_opp_{c}"].to_numpy(dtype="float64")
    merged = merged.drop(columns=[f"_opp_{c}" for c in pred_cols])
    return pd.concat([merged, pd.DataFrame(out, index=merged.index)], axis=1)
