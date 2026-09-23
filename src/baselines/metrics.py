"""Metricas de avaliacao (item 5 da instrucao da Fase 4).

Todas as funcoes ignoram pares (y_true, y_pred) onde qualquer um dos dois e
NA -- nunca preenchem ausencia com 0/media (mesma regra da Fase 2/3).
Retornam None (nao 0.0) quando nao ha nenhum par valido, para que a
ausencia de cobertura fique explicita nos relatorios em vez de aparecer
como "erro zero".
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _valid_pairs(y_true, y_pred):
    yt = pd.to_numeric(pd.Series(y_true), errors="coerce").to_numpy(dtype="float64")
    yp = pd.to_numeric(pd.Series(y_pred), errors="coerce").to_numpy(dtype="float64")
    mask = np.isfinite(yt) & np.isfinite(yp)
    return yt[mask], yp[mask]


def numeric_metrics(y_true, y_pred) -> dict:
    yt, yp = _valid_pairs(y_true, y_pred)
    n = yt.size
    if n == 0:
        return {"n": 0, "mae": None, "rmse": None, "mean_error": None,
                "corr": None, "pred_mean": None, "actual_mean": None,
                "pred_var": None, "actual_var": None}
    err = yp - yt
    corr = float(np.corrcoef(yt, yp)[0, 1]) if n >= 2 and np.std(yt) > 0 and np.std(yp) > 0 else None
    return {
        "n": int(n),
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "mean_error": float(np.mean(err)),  # bias: positivo = superestima
        "corr": corr,
        "pred_mean": float(np.mean(yp)),
        "actual_mean": float(np.mean(yt)),
        "pred_var": float(np.var(yp)),
        "actual_var": float(np.var(yt)),
    }


def count_overdispersion(y_true) -> dict:
    """Razao variancia/media do alvo observado (>1 sugere Negative Binomial
    em vez de Poisson, que assume variancia == media)."""
    yt = pd.to_numeric(pd.Series(y_true), errors="coerce").dropna().to_numpy(dtype="float64")
    if yt.size == 0:
        return {"n": 0, "mean": None, "var": None, "dispersion_ratio": None, "overdispersed": None}
    mean = float(np.mean(yt))
    var = float(np.var(yt))
    ratio = (var / mean) if mean > 0 else None
    return {
        "n": int(yt.size), "mean": mean, "var": var,
        "dispersion_ratio": ratio,
        "overdispersed": (ratio is not None and ratio > 1.15),
    }


def brier_score(y_true_binary, p_pred) -> dict:
    yt, yp = _valid_pairs(y_true_binary, p_pred)
    n = yt.size
    if n == 0:
        return {"n": 0, "brier": None, "log_loss": None}
    yp_c = np.clip(yp, 1e-6, 1 - 1e-6)
    brier = float(np.mean((yp_c - yt) ** 2))
    log_loss = float(-np.mean(yt * np.log(yp_c) + (1 - yt) * np.log(1 - yp_c)))
    return {"n": int(n), "brier": brier, "log_loss": log_loss}


def calibration_curve(y_true_binary, p_pred, n_bins: int = 10) -> pd.DataFrame:
    yt, yp = _valid_pairs(y_true_binary, p_pred)
    if yt.size == 0:
        return pd.DataFrame(columns=["bin", "bin_lo", "bin_hi", "n", "pred_mean", "actual_rate"])
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(yp, bins) - 1, 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        mask = idx == b
        n = int(mask.sum())
        rows.append({
            "bin": b, "bin_lo": float(bins[b]), "bin_hi": float(bins[b + 1]),
            "n": n,
            "pred_mean": float(yp[mask].mean()) if n > 0 else None,
            "actual_rate": float(yt[mask].mean()) if n > 0 else None,
        })
    return pd.DataFrame(rows)


def calibration_error(y_true_binary, p_pred, n_bins: int = 10):
    """Expected Calibration Error (media ponderada por bin do |pred-real|)."""
    cc = calibration_curve(y_true_binary, p_pred, n_bins=n_bins)
    cc = cc.dropna(subset=["pred_mean", "actual_rate"])
    total_n = cc["n"].sum()
    if total_n == 0:
        return None
    return float((cc["n"] * (cc["pred_mean"] - cc["actual_rate"]).abs()).sum() / total_n)
