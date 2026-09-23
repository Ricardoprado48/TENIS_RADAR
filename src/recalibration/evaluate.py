"""Avaliacao antes x depois (item 4/5/6/7): Brier, Log Loss, ECE e curva de
confiabilidade, por metodo e por segmento. Reaproveita as funcoes ja
testadas na Fase 4 (src/baselines/metrics.py)."""

from __future__ import annotations

import pandas as pd

from src.baselines.metrics import brier_score, calibration_curve, calibration_error

from . import config as cfg


def metrics_by_group(df: pd.DataFrame, actual_col: str, method_cols: dict[str, str],
                      group_cols: list[str]) -> pd.DataFrame:
    """`method_cols`: {"raw": "raw_probability", "platt": "platt_probability", ...}.
    Uma linha por (grupo, metodo)."""

    rows = []
    for key, sub in df.groupby(group_cols, dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        for method, col in method_cols.items():
            valid = sub[col].notna()
            b = brier_score(sub.loc[valid, actual_col], sub.loc[valid, col])
            ce = calibration_error(sub.loc[valid, actual_col], sub.loc[valid, col]) if b["n"] and b["n"] >= 20 else None
            row = dict(zip(group_cols, key))
            row.update({"method": method, "n": b["n"], "brier": b["brier"], "log_loss": b["log_loss"], "ece": ce})
            rows.append(row)
    return pd.DataFrame(rows)


def probability_bucket(p: pd.Series) -> pd.Series:
    import numpy as np
    edges = cfg.PROB_BUCKET_EDGES
    labels = cfg.PROB_BUCKET_LABELS
    idx = np.clip(np.digitize(p.to_numpy(dtype="float64"), edges[1:-1], right=False), 0, len(labels) - 1)
    return pd.Series([labels[i] for i in idx], index=p.index)


def reliability_by_bucket(df: pd.DataFrame, actual_col: str, prob_col: str,
                           group_cols: list[str]) -> pd.DataFrame:
    """Frequencia real por bucket de probabilidade PREVISTA (item 5), com n
    por bucket e a flag de amostra insuficiente (item 5: 'marcar
    explicitamente')."""

    d = df.copy()
    d = d[d[prob_col].notna()]
    d["prob_bucket"] = probability_bucket(d[prob_col])
    rows = []
    for key, sub in d.groupby(group_cols + ["prob_bucket"], dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        n = len(sub)
        row = dict(zip(group_cols + ["prob_bucket"], key))
        row.update({
            "n": n,
            "pred_mean": float(sub[prob_col].mean()) if n > 0 else None,
            "actual_rate": float(sub[actual_col].mean()) if n > 0 else None,
            "amostra_insuficiente": n < cfg.MIN_BUCKET_N_FOR_REPORT,
        })
        rows.append(row)
    out = pd.DataFrame(rows)
    if not out.empty:
        cat = pd.Categorical(out["prob_bucket"], categories=cfg.PROB_BUCKET_LABELS, ordered=True)
        out["prob_bucket"] = cat
        out = out.sort_values(group_cols + ["prob_bucket"]).reset_index(drop=True)
    return out
