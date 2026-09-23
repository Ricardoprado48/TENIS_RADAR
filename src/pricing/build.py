"""Orquestrador da Fase 7: converte a probabilidade operacional ja definida
na Fase 6.1 em odd justa e odd minima aceitavel por cenario de edge, com
flags de qualidade e restricao. Nao ajusta nenhum modelo nem calibrador
novo -- so consome `data/outputs/phase6/previsoes_por_linha.parquet`
(contexto) e `data/outputs/phase6_1/previsoes_calibradas.parquet`
(probabilidade operacional) e grava em `data/outputs/phase7/`.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import config as cfg
from . import flags as fl
from . import odds


_CONTEXT_COLS = [
    "tour", "market", "fold", "match_id", "player_id", "line",
    "surface", "prior_matches_career", "sample_bucket_career", "line_difficulty",
]
_PROB_COLS = [
    "tour", "market", "fold", "match_id", "player_id", "line",
    "raw_probability", "calibrated_probability", "method_selected", "calibrator_train_n",
]


def load_merged() -> pd.DataFrame:
    ctx = pd.read_parquet(cfg.PHASE6_PREDICTIONS_PATH, columns=_CONTEXT_COLS)
    prob = pd.read_parquet(cfg.PHASE6_1_PREDICTIONS_PATH, columns=_PROB_COLS)
    merged = ctx.merge(prob, on=cfg.JOIN_KEYS, how="inner", validate="one_to_one")
    return merged


def build_base(merged: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por (contexto, linha .5): probabilidade operacional (item 1:
    "calibrada quando o calibrador foi aprovado; raw quando recalibracao nao
    trouxe ganho" -- e exatamente `calibrated_probability` da Fase 6.1, que
    ja implementa essa regra) para os dois lados, sem descartar
    raw_probability nem o metodo usado (item 1: "nunca substituir
    silenciosamente")."""

    df = merged.copy()
    df["operational_probability_over"] = df["calibrated_probability"]
    df["operational_probability_under"] = 1.0 - df["calibrated_probability"]
    df["raw_probability_over"] = df["raw_probability"]
    df["raw_probability_under"] = 1.0 - df["raw_probability"]

    df["cold_start"] = fl.cold_start_flag(df["sample_bucket_career"])
    df["insufficient_history"] = fl.insufficient_history_flag(df["sample_bucket_career"])
    df["calibrator_insufficient_sample"] = fl.calibrator_insufficient_sample_flag(
        df["calibrator_train_n"], df["method_selected"])
    restricted, restricted_motivo = fl.restricted_flag(df["tour"], df["market"], df["surface"])
    df["restricted"] = restricted
    df["restricted_motivo"] = restricted_motivo

    return df


def _side_frame(base: pd.DataFrame, side: str) -> pd.DataFrame:
    p_op = base[f"operational_probability_{side}"].to_numpy(dtype="float64")
    p_raw = base[f"raw_probability_{side}"].to_numpy(dtype="float64")

    fair = odds.fair_odds(p_op)
    # item 6: cold start nunca recebe preco, mesmo que a probabilidade
    # tecnicamente exista.
    fair = np.where(base["cold_start"].to_numpy(), np.nan, fair)

    extreme = fl.extreme_probability_flag(pd.Series(p_op, index=base.index))

    out = pd.DataFrame({
        "tour": base["tour"].to_numpy(),
        "market": base["market"].to_numpy(),
        "fold": base["fold"].to_numpy(),
        "surface": base["surface"].to_numpy(),
        "match_id": base["match_id"].to_numpy(),
        "player_id": base["player_id"].to_numpy(),
        "line": base["line"].to_numpy(),
        "side": side,
        "prior_matches_career": base["prior_matches_career"].to_numpy(),
        "sample_bucket_career": base["sample_bucket_career"].to_numpy(),
        "line_difficulty": base["line_difficulty"].to_numpy(),
        "raw_probability": p_raw,
        "calibrated_probability": p_op,
        "operational_probability": p_op,
        "method_selected": base["method_selected"].to_numpy(),
        "calibrator_train_n": base["calibrator_train_n"].to_numpy(),
        "fair_odds": fair,
        "cold_start": base["cold_start"].to_numpy(),
        "insufficient_history": base["insufficient_history"].to_numpy(),
        "calibrator_insufficient_sample": base["calibrator_insufficient_sample"].to_numpy(),
        "extreme_probability": extreme.to_numpy(),
        "restricted": base["restricted"].to_numpy(),
        "restricted_motivo": base["restricted_motivo"].to_numpy(),
    })
    return out


def build_prices_by_line(base: pd.DataFrame) -> pd.DataFrame:
    return pd.concat([_side_frame(base, side) for side in cfg.SIDES], ignore_index=True)


def build_minimum_odds_by_edge(prices: pd.DataFrame) -> pd.DataFrame:
    """Tabela longa (item 11): uma linha por (linha, lado, cenario de edge)
    com a odd minima aceitavel. Nao decide qual edge usar (item 10)."""

    parts = []
    for label, e in cfg.EDGE_LEVELS:
        p = prices["operational_probability"].to_numpy(dtype="float64")
        min_odds = odds.minimum_acceptable_odds(p, e)
        min_odds = np.where(prices["cold_start"].to_numpy(), np.nan, min_odds)
        part = prices[["tour", "market", "fold", "surface", "match_id", "player_id",
                        "line", "side", "operational_probability", "cold_start", "restricted"]].copy()
        part["edge_requerido"] = e
        part["edge_label"] = label
        part["p_implicita_maxima"] = np.where(prices["cold_start"].to_numpy(), np.nan, p - e)
        part["odd_minima"] = min_odds
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def _check_monotonicity(base: pd.DataFrame) -> pd.DataFrame:
    """item 7: conforme a linha de Over aumenta, p(Over) deve cair (e a odd
    justa de Over deve subir); verificado sobre dados reais do pipeline, nao
    so em teste unitario sintetico."""

    group_cols = ["tour", "market", "fold", "surface", "match_id", "player_id"]
    rows = []
    for key, g in base.sort_values("line").groupby(group_cols, dropna=False, sort=False):
        if len(g) < 2:
            continue
        p = g["operational_probability_over"].to_numpy(dtype="float64")
        diffs = np.diff(p)
        ok = bool(np.all(diffs <= 1e-9))
        key = key if isinstance(key, tuple) else (key,)
        row = dict(zip(group_cols, key))
        row["n_lines"] = len(g)
        row["monotonic_ok"] = ok
        rows.append(row)
    return pd.DataFrame(rows)


def _sample_examples(prices: pd.DataFrame, n_groups: int = 10) -> pd.DataFrame:
    non_cold = prices[~prices["cold_start"]]
    keys = non_cold[["tour", "market", "fold", "match_id", "player_id"]].drop_duplicates()
    sample_keys = keys.sample(n=min(n_groups, len(keys)), random_state=cfg.RANDOM_SEED)
    examples = non_cold.merge(sample_keys, on=["tour", "market", "fold", "match_id", "player_id"])
    return examples.sort_values(["tour", "market", "match_id", "player_id", "side", "line"])


def run() -> dict:
    cfg.PHASE7_DIR.mkdir(parents=True, exist_ok=True)

    merged = load_merged()
    base = build_base(merged)

    prices = build_prices_by_line(base)
    prices.to_parquet(cfg.PHASE7_DIR / "precos_por_linha.parquet", index=False)

    min_odds = build_minimum_odds_by_edge(prices)
    min_odds.to_parquet(cfg.PHASE7_DIR / "odds_minimas_por_edge.parquet", index=False)

    mono = _check_monotonicity(base)
    mono.to_csv(cfg.PHASE7_DIR / "verificacao_monotonicidade.csv", index=False)
    mono_summary = (
        mono.groupby(["tour", "market"])["monotonic_ok"]
        .agg(["size", "sum"]).reset_index()
        .rename(columns={"size": "n_grupos", "sum": "n_monotonicos"})
    )
    mono_summary["pct_monotonico"] = mono_summary["n_monotonicos"] / mono_summary["n_grupos"]
    mono_summary.to_csv(cfg.PHASE7_DIR / "verificacao_monotonicidade_resumo.csv", index=False)

    flag_cols = ["cold_start", "insufficient_history", "calibrator_insufficient_sample",
                 "extreme_probability", "restricted"]
    resumo_flags = (
        prices.groupby(["tour", "market", "side"])[flag_cols]
        .agg(["sum", "count"]).reset_index()
    )
    resumo_flags.columns = ["_".join(c).strip("_") for c in resumo_flags.columns]
    resumo_flags.to_csv(cfg.PHASE7_DIR / "resumo_flags.csv", index=False)

    examples = _sample_examples(prices)
    examples.to_csv(cfg.PHASE7_DIR / "exemplos_precos.csv", index=False)

    example_edges = min_odds.merge(
        examples[["tour", "market", "fold", "match_id", "player_id", "line", "side"]].drop_duplicates(),
        on=["tour", "market", "fold", "match_id", "player_id", "line", "side"],
    )
    example_edges.to_csv(cfg.PHASE7_DIR / "exemplos_odds_minimas_por_edge.csv", index=False)

    summary = {
        "n_rows_context": int(len(merged)),
        "n_rows_prices": int(len(prices)),
        "n_rows_minimum_odds": int(len(min_odds)),
        "classification": {f"{t}__{m}": v for (t, m), v in cfg.PHASE6_1_CLASSIFICATION.items()},
        "restricted_segments": cfg.RESTRICTED_SEGMENTS,
        "edge_levels": cfg.EDGE_LEVELS,
        "monotonicity_summary": mono_summary.to_dict(orient="records"),
        "flag_counts": {
            flag: int(prices[flag].sum()) for flag in flag_cols
        },
    }
    with open(cfg.PHASE7_DIR / "phase7_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    return summary
