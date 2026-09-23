"""Poisson vs Negative Binomial (item 2: "Poisson; Negative Binomial se
houver overdispersion"; item 5: "avaliar tambem: media prevista vs real,
variancia prevista vs real, overdispersion").

Metodologia: o baseline de taxa (rate_models.py) ja fornece a media
prevista (lambda) por linha -- Poisson/NegBin NAO sao usados aqui para
REFAZER essa previsao de media, e sim para transformar a previsao pontual
em uma previsao PROBABILISTICA (item 5 pede Brier/Log Loss/calibracao
"para probabilidades"), o que uma previsao de contagem pura nao da sozinha.

Um limiar fixo (a MEDIANA do alvo real no fold de TREINO -- nunca no
teste) define o evento binario "resultado acima do limiar". Poisson usa
lambda = previsao da linha; Negative Binomial usa o MESMO lambda por linha
mas um parametro de dispersao `r` estimado por metodo dos momentos
SOMENTE no fold de treino (media/variancia do alvo real de treino) -- ou
seja, a FORMA da distribuicao (o quanto a variancia excede a media) vem do
treino, mas a media condicional (lambda) continua sendo por partida,
point-in-time, como ja calculado.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .metrics import brier_score, count_overdispersion


def fit_negbin_r(train_actual: pd.Series) -> float | None:
    """Metodo dos momentos: var = mean + mean^2/r  =>  r = mean^2/(var-mean).
    Retorna None se nao houver overdispersion detectavel no treino (nesse
    caso o proprio Poisson ja e adequado, e NegBin nao teria dispersao
    finita bem definida)."""
    disp = count_overdispersion(train_actual)
    if disp["mean"] is None or disp["var"] is None or disp["var"] <= disp["mean"]:
        return None
    return float(disp["mean"] ** 2 / (disp["var"] - disp["mean"]))


def evaluate_count_market(train_df: pd.DataFrame, test_df: pd.DataFrame,
                           actual_col: str, pred_col: str) -> dict:
    """Retorna diagnosticos (overdispersion do treino) + Brier/LogLoss de
    Poisson e Negative Binomial no fold de TESTE, usando um limiar fixo
    (mediana do treino)."""

    train_actual = pd.to_numeric(train_df[actual_col], errors="coerce").dropna()
    disp = count_overdispersion(train_actual)
    if len(train_actual) == 0:
        return {"train_dispersion": disp, "threshold": None, "poisson": None, "negbin": None, "r": None}

    threshold = float(train_actual.median())
    r = fit_negbin_r(train_actual)

    test_actual = pd.to_numeric(test_df[actual_col], errors="coerce")
    test_pred = pd.to_numeric(test_df[pred_col], errors="coerce")
    mask = test_actual.notna() & test_pred.notna() & (test_pred > 0)
    yt = test_actual[mask].to_numpy(dtype="float64")
    lam = test_pred[mask].to_numpy(dtype="float64")
    if yt.size == 0:
        return {"train_dispersion": disp, "threshold": threshold, "poisson": None, "negbin": None, "r": r}

    actual_binary = (yt > threshold).astype("float64")

    p_over_poisson = stats.poisson.sf(threshold, mu=lam)
    poisson_eval = brier_score(actual_binary, p_over_poisson)
    poisson_eval["mean_pred_lambda"] = float(np.mean(lam))
    poisson_eval["mean_actual"] = float(np.mean(yt))
    poisson_eval["var_actual"] = float(np.var(yt))
    # Poisson assume var(previsto) == media(previsto); comparamos contra a
    # variancia real observada no MESMO fold de teste (nao usada para
    # ajustar nada, so para diagnostico -- item 5).
    poisson_eval["var_implied_by_model"] = float(np.mean(lam))

    negbin_eval = None
    if r is not None and r > 0:
        p_r = r / (r + lam)
        p_over_negbin = stats.nbinom.sf(threshold, r, p_r)
        negbin_eval = brier_score(actual_binary, p_over_negbin)
        negbin_eval["mean_pred_lambda"] = float(np.mean(lam))
        negbin_eval["r"] = r
        negbin_eval["var_implied_by_model"] = float(np.mean(lam + (lam ** 2) / r))

    return {
        "train_dispersion": disp, "threshold": threshold, "r": r,
        "poisson": poisson_eval, "negbin": negbin_eval,
    }
