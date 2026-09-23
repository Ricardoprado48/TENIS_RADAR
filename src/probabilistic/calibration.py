"""Metricas de calibracao (item 6/7/8) -- reaproveita as funcoes ja
implementadas e testadas na Fase 4 (src/baselines/metrics.py: brier_score,
calibration_curve, calibration_error) em vez de reimplementar Brier/ECE."""

from __future__ import annotations

import pandas as pd

from src.baselines.metrics import brier_score, calibration_curve, calibration_error


def segment_metrics(df: pd.DataFrame, actual_col: str, pred_col: str,
                     group_cols: list[str]) -> pd.DataFrame:
    """Brier/LogLoss/ECE agrupados por `group_cols` (fold, superficie, tour,
    bucket de amostra, bucket de dificuldade de linha, etc.)."""

    rows = []
    for key, sub in df.groupby(group_cols, dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        b = brier_score(sub[actual_col], sub[pred_col])
        ce = calibration_error(sub[actual_col], sub[pred_col]) if b["n"] and b["n"] >= 20 else None
        row = dict(zip(group_cols, key))
        row.update({"n": b["n"], "brier": b["brier"], "log_loss": b["log_loss"], "ece": ce})
        rows.append(row)
    return pd.DataFrame(rows)


def reliability_table(df: pd.DataFrame, actual_col: str, pred_col: str,
                       n_bins: int = 10, group_cols: list[str] | None = None) -> pd.DataFrame:
    """Curva de calibracao (bucket de probabilidade prevista -> frequencia
    real), opcionalmente quebrada por `group_cols` (item 6: "previsoes entre
    60-65% devem ocorrer aproximadamente nessa frequencia")."""

    if not group_cols:
        cc = calibration_curve(df[actual_col], df[pred_col], n_bins=n_bins)
        cc.insert(0, "group", "overall")
        return cc

    parts = []
    for key, sub in df.groupby(group_cols, dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        cc = calibration_curve(sub[actual_col], sub[pred_col], n_bins=n_bins)
        for col, val in zip(group_cols, key):
            cc.insert(0, col, val)
        parts.append(cc)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
