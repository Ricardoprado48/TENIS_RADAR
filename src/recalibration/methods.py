"""Metodos de calibracao (item 2): raw (sem calibracao), Platt/logistic
scaling, Isotonic regression. Nenhum metodo complexo alem desses dois,
padrao na literatura de calibracao de probabilidades.

Platt scaling: regressao logistica de 1 variavel sobre o logit da
probabilidade bruta (`logit(p_calibrado) = a * logit(p_bruto) + b`),
ajustada por maxima verossimilhanca (sklearn.linear_model.LogisticRegression).
Preserva monotonicidade em relacao a p_bruto sempre que o coeficiente `a`
ajustado for positivo -- checado explicitamente, com fallback para raw caso
contrario (ver `fit_platt`).

Isotonic regression: sklearn.isotonic.IsotonicRegression, monotona por
construcao (nunca precisa do checkout acima).
"""

from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from . import config as cfg

_EPS = 1e-6


def _logit(p: np.ndarray) -> np.ndarray:
    p_c = np.clip(p, _EPS, 1 - _EPS)
    return np.log(p_c / (1 - p_c))


class RawCalibrator:
    method = "raw"

    def predict(self, p_raw: np.ndarray) -> np.ndarray:
        return np.asarray(p_raw, dtype="float64")


class PlattCalibrator:
    method = "platt"

    def __init__(self, clf: LogisticRegression):
        self._clf = clf

    def predict(self, p_raw: np.ndarray) -> np.ndarray:
        x = _logit(np.asarray(p_raw, dtype="float64")).reshape(-1, 1)
        return self._clf.predict_proba(x)[:, 1]


class IsotonicCalibrator:
    method = "isotonic"

    def __init__(self, iso: IsotonicRegression):
        self._iso = iso

    def predict(self, p_raw: np.ndarray) -> np.ndarray:
        return self._iso.predict(np.asarray(p_raw, dtype="float64"))


def fit_platt(p_raw: np.ndarray, y: np.ndarray) -> PlattCalibrator | None:
    x = _logit(np.asarray(p_raw, dtype="float64")).reshape(-1, 1)
    yy = np.asarray(y, dtype="float64")
    if len(np.unique(yy)) < 2:
        return None
    clf = LogisticRegression(solver="lbfgs")
    clf.fit(x, yy)
    # monotonicidade em relacao a p_bruto exige coeficiente positivo -- se o
    # ajuste "inverter" a relacao (sinal de amostra degenerada/ruido, nao um
    # calibrador de verdade), descartamos em vez de aplicar (item 12:
    # fallback seguro).
    if clf.coef_[0][0] <= 0:
        return None
    return PlattCalibrator(clf)


def fit_isotonic(p_raw: np.ndarray, y: np.ndarray) -> IsotonicCalibrator | None:
    x = np.asarray(p_raw, dtype="float64")
    yy = np.asarray(y, dtype="float64")
    if len(np.unique(yy)) < 2:
        return None
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    iso.fit(x, yy)
    return IsotonicCalibrator(iso)


def fit_calibrator(method: str, p_raw: np.ndarray, y: np.ndarray, min_n: int = cfg.MIN_CALIBRATOR_TRAIN_N):
    """Retorna (calibrator, status). status descreve por que um fallback
    para `raw` foi (ou nao) usado -- nunca falha silenciosamente."""

    n = len(p_raw)
    if n < min_n:
        return RawCalibrator(), f"raw_amostra_insuficiente (n={n} < {min_n})"
    if method == "raw":
        return RawCalibrator(), "raw"
    if method == "platt":
        model = fit_platt(p_raw, y)
        return (model, "platt") if model is not None else (RawCalibrator(), "raw_platt_degenerado")
    if method == "isotonic":
        model = fit_isotonic(p_raw, y)
        return (model, "isotonic") if model is not None else (RawCalibrator(), "raw_isotonic_degenerado")
    raise ValueError(f"metodo desconhecido: {method}")
