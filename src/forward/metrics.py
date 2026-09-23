"""Metricas preditivas e de preco (itens 9, 10, 12, 13, 15) -- calculadas
SOMENTE sobre oportunidades ja settled em WIN/LOSS (outcome binario
definido). VOID/UNRESOLVED/BOOKMAKER_RULE_REQUIRED sao excluidas das
metricas de probabilidade (o outcome do mercado nao esta definido), mas
continuam contadas separadamente (`paper_test.py`) para transparencia.

Limitacao registrada (ver docs/017): o projeto nao produz um valor pontual
previsto de contagem (so `probabilidade de Over/Under uma linha`), entao
MAE/RMSE de contagem (usados nas Fases 4-6 para os modelos brutos) nao sao
recalculados aqui -- Brier Score, Log Loss e calibracao por bucket cobrem a
qualidade da PROBABILIDADE, que e o que de fato alimenta a decisao
operacional da Fase 10."""

from __future__ import annotations

import math

import pandas as pd

from . import config as cfg

_EPS = 1e-9


def with_outcome(predictions: pd.DataFrame, settlements: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty or settlements.empty:
        return pd.DataFrame()
    merged = predictions.merge(settlements[["prediction_id", "settlement"]], on="prediction_id", how="inner")
    merged = merged[merged["settlement"].isin([cfg.SETTLEMENT_WIN, cfg.SETTLEMENT_LOSS])].copy()
    if merged.empty:
        return merged
    merged["outcome"] = (merged["settlement"] == cfg.SETTLEMENT_WIN).astype(int)
    return merged


def brier_score(df: pd.DataFrame):
    if df.empty:
        return None
    p = df["operational_probability"].astype(float)
    y = df["outcome"].astype(float)
    return float(((p - y) ** 2).mean())


def log_loss(df: pd.DataFrame):
    if df.empty:
        return None
    p = df["operational_probability"].astype(float).clip(_EPS, 1 - _EPS)
    y = df["outcome"].astype(float)
    return float(-(y * p.apply(math.log) + (1 - y) * (1 - p).apply(math.log)).mean())


def calibration_by_bucket(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    edges = cfg.CALIBRATION_BUCKET_EDGES
    labels = [f"{int(edges[i] * 100)}-{int(edges[i + 1] * 100)}%" for i in range(len(edges) - 1)]
    out = df.copy()
    out["bucket"] = pd.cut(out["operational_probability"], bins=edges, labels=labels, include_lowest=True)
    g = out.groupby("bucket", observed=False).agg(
        n=("outcome", "size"),
        mean_predicted=("operational_probability", "mean"),
        observed_rate=("outcome", "mean"),
    ).reset_index()
    return g


def _grouped_metrics(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    if df.empty or group_col not in df.columns:
        return pd.DataFrame()
    rows = []
    for key, g in df.groupby(group_col, dropna=False):
        rows.append({
            "dimension": group_col, "group": key,
            "n": int(len(g)), "brier_score": brier_score(g), "log_loss": log_loss(g),
            "observed_win_rate": float(g["outcome"].mean()),
        })
    return pd.DataFrame(rows)


def sample_size_checkpoints(n_total: int) -> list[dict]:
    """item 15: SOMENTE descritivo -- nunca uma regra automatica de
    aprovacao/reprovacao do modelo baseada so na quantidade."""
    return [{"checkpoint": c, "reached": n_total >= c} for c in cfg.SAMPLE_SIZE_CHECKPOINTS]


def threshold_comparison(df_with_outcome: pd.DataFrame, paper_test: pd.DataFrame) -> pd.DataFrame:
    """item 12: frequencia de cada threshold de edge (Fase 10) e o
    resultado associado (amostra, taxa observada, Brier, ROI em paper test)
    -- comparados lado a lado, sem escolher vencedor (item 12: "nao
    interpretar isoladamente" / nao antecipar um padrao definitivo)."""

    rows = []
    for label in cfg.EDGE_THRESHOLD_LABELS_CUMULATIVE:
        min_rank = cfg.EDGE_RANK[label]
        if df_with_outcome.empty:
            subset = df_with_outcome
        else:
            subset = df_with_outcome[df_with_outcome["status"].map(lambda s: cfg.EDGE_RANK.get(s, 0)) >= min_rank]

        pt_resolved = pd.DataFrame()
        if not paper_test.empty and not subset.empty:
            pt_subset = paper_test[paper_test["prediction_id"].isin(subset["prediction_id"])]
            pt_resolved = pt_subset[pt_subset["pnl_units"].notna()] if not pt_subset.empty else pt_resolved

        rows.append({
            "edge_threshold": label,
            "n_settled_win_loss": int(len(subset)),
            "observed_win_rate": float(subset["outcome"].mean()) if not subset.empty else None,
            "brier_score": brier_score(subset),
            "n_paper_test_resolved": int(len(pt_resolved)),
            "paper_test_roi": (
                float(pt_resolved["pnl_units"].sum() / len(pt_resolved)) if not pt_resolved.empty else None
            ),
        })
    return pd.DataFrame(rows)


def classification_comparison(predictions: pd.DataFrame, settlements: pd.DataFrame, paper_test: pd.DataFrame) -> pd.DataFrame:
    """item 13: compara DESCARTAR/OBSERVAR/CANDIDATO_FRACO/CANDIDATO/
    CANDIDATO_FORTE entre si -- responde se a camada da Fase 10 realmente
    separa situacoes melhores das piores."""

    if predictions.empty or settlements.empty:
        return pd.DataFrame()

    merged = predictions.merge(settlements[["prediction_id", "settlement"]], on="prediction_id", how="left")
    rows = []
    for classification, g in merged.groupby("classification"):
        resolved = g[g["settlement"].isin([cfg.SETTLEMENT_WIN, cfg.SETTLEMENT_LOSS])]
        pt_resolved = pd.DataFrame()
        if not paper_test.empty:
            pt_subset = paper_test[paper_test["prediction_id"].isin(g["prediction_id"])]
            pt_resolved = pt_subset[pt_subset["pnl_units"].notna()] if not pt_subset.empty else pt_resolved

        rows.append({
            "classification": classification,
            "n_registered": int(len(g)),
            "n_settled_win_loss": int(len(resolved)),
            "observed_win_rate": (
                float((resolved["settlement"] == cfg.SETTLEMENT_WIN).mean()) if not resolved.empty else None
            ),
            "n_paper_test_resolved": int(len(pt_resolved)),
            "paper_test_roi": (
                float(pt_resolved["pnl_units"].sum() / len(pt_resolved)) if not pt_resolved.empty else None
            ),
        })
    return pd.DataFrame(rows)


def build_forward_metrics(predictions: pd.DataFrame, settlements: pd.DataFrame) -> pd.DataFrame:
    df = with_outcome(predictions, settlements)
    if df.empty:
        return pd.DataFrame()

    parts = [pd.DataFrame([{
        "dimension": "overall", "group": "ALL",
        "n": int(len(df)), "brier_score": brier_score(df), "log_loss": log_loss(df),
        "observed_win_rate": float(df["outcome"].mean()),
    }])]
    for dim in ["market", "tour", "surface_ctx"]:
        g = _grouped_metrics(df, dim)
        if not g.empty:
            parts.append(g)

    out = pd.concat(parts, ignore_index=True)
    cfg.PHASE11_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cfg.FORWARD_METRICS_PATH, index=False)
    return out
