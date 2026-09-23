"""Baseline "media historica do jogador" (o primeiro baseline pedido para
aces/double faults, e a base do baseline de total de games por media
simples) -- reaproveita o MESMO motor point-in-time da Fase 3
(src.features.rolling.compute_windowed_priors/compute_decay_priors) para
somar os ALVOS observados (aces, double_faults, total_games, game_diff,
has_tiebreak) das partidas ANTERIORES de cada jogador, nas mesmas 7 janelas
da Fase 3. A CONTAGEM de partidas anteriores (denominador) e reaproveitada
das colunas `prior_matches_{janela}`/`surface_prior_matches` que ja existem
na tabela de features -- nao recalculada.

Isso NAO e uma nova versao da Fase 3: e um modelo da Fase 4 (baseline de
media historica), construido sobre os MESMOS alvos usados so como rotulo em
targets.py, aplicando o motor de agregacao point-in-time ja testado (25
testes anti-leakage na Fase 3) a colunas diferentes (o resultado observado,
em vez de taxas de saque/devolucao).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.config import DEFAULT_DECAY_HALFLIFE_DAYS
from src.features.profile import ALL_WINDOW_NAMES, DECAY_SUFFIX
from src.features.rolling import compute_decay_priors, compute_windowed_priors

_VALUE_COLS = [
    "target_aces", "target_double_faults", "target_total_games",
    "target_game_diff", "target_total_aces_match", "target_has_tiebreak",
]


def _non_surface_windows() -> dict:
    from src.features.config import LAST_N_WINDOWS, TIME_WINDOWS_DAYS
    windows = {"career": {"type": "all_prior"}}
    for name, n in LAST_N_WINDOWS.items():
        windows[name] = {"type": "last_n", "n": n}
    for name, days in TIME_WINDOWS_DAYS.items():
        windows[name] = {"type": "time", "days": days}
    return windows


def build_history_mean_priors(df_with_targets: pd.DataFrame) -> pd.DataFrame:
    """Recebe a tabela de features+targets de UM tour (na MESMA ordem
    cronologica gravada pela Fase 3) e retorna, alinhado ao mesmo index,
    `hist_mean_{value}_{window}` para cada alvo em _VALUE_COLS e cada janela
    de ALL_WINDOW_NAMES, dividindo pela contagem de partidas anteriores ja
    existente na propria tabela (prior_matches_{window} / surface_prior_matches)."""

    df = df_with_targets.reset_index(drop=True)
    df["_seq"] = df.index

    value_cols_present = [c for c in _VALUE_COLS if c in df.columns]
    vals = df[value_cols_present].astype("float64")
    for c in value_cols_present:
        df[c] = vals[c].fillna(0.0)  # preenchimento transitorio -- ver docs/007 secao 5 / docs/008 secao 3

    priors = compute_windowed_priors(
        df, ["player_id"], "tournament_date", "_seq", value_cols_present, _non_surface_windows(),
    )

    has_surface = df["surface"].notna()
    surface_partial = compute_windowed_priors(
        df.loc[has_surface], ["player_id", "surface"], "tournament_date", "_seq",
        value_cols_present, {"surface_career": {"type": "all_prior"}},
    )
    surface_priors = surface_partial.reindex(df.index)

    # para decay90d, o denominador de uma MEDIA precisa ser o "N efetivo"
    # DECAIDO (soma dos pesos de decaimento), nao a contagem bruta de
    # partidas -- ao contrario da Fase 3, onde numerador E denominador de
    # uma TAXA sao ambos decaidos (ex. aces decaido / service_points
    # decaido), aqui o numerador e uma soma decaida mas nao ha "denominador"
    # natural: dividir pela contagem bruta subestima sistematicamente a
    # media sempre que houver um hiato de tempo (o numerador decai, o
    # denominador nao). Corrigido incluindo uma pseudo-coluna de valor 1.0
    # entre os `value_cols` decaidos, para obter o N efetivo decaido pelo
    # MESMO mecanismo (nao um novo calculo). Achado durante a verificacao
    # dos resultados da Fase 4 -- ver docs/008 secao 3.
    decay_value_cols = value_cols_present + ["_decay_weight_one"]
    df["_decay_weight_one"] = 1.0
    decay_priors = compute_decay_priors(
        df, ["player_id"], "tournament_date", "_seq", decay_value_cols,
        float(DEFAULT_DECAY_HALFLIFE_DAYS), DECAY_SUFFIX,
    )
    decay_effective_n = decay_priors[f"_decay_weight_one__{DECAY_SUFFIX}"].to_numpy(dtype="float64")

    priors_all = pd.concat([priors, surface_priors, decay_priors], axis=1)

    out = {}
    for window in ALL_WINDOW_NAMES:
        if window == "surface_career":
            n_col = df["surface_prior_matches"].to_numpy(dtype="float64")
        elif window == DECAY_SUFFIX:
            n_col = decay_effective_n
        else:
            n_col = df[f"prior_matches_{window}"].to_numpy(dtype="float64")
        for value_col in value_cols_present:
            num = priors_all[f"{value_col}__{window}"].to_numpy(dtype="float64")
            with np.errstate(divide="ignore", invalid="ignore"):
                mean = np.where(n_col > 0, num / n_col, np.nan)
            short_name = value_col.replace("target_", "")
            out[f"hist_mean_{short_name}_{window}"] = mean

    return pd.DataFrame(out, index=df_with_targets.index)
