"""Runner da Fase 4: monta a tabela completa por tour, roda a avaliacao
walk-forward, e grava previsoes/metricas em data/outputs/phase4/."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.normalization.config import TOURS

from .config import FOLDS, PHASE4_CONFIG_DIR, PHASE4_METRICS_DIR, PHASE4_PREDICTIONS_DIR
from .evaluate import build_tour_table, evaluate_numeric_markets, evaluate_prob_markets
from .walkforward import iter_folds

_KEEP_CONTEXT = [
    "match_id", "tour", "player_id", "opponent_id", "tournament_date", "surface",
    "tourney_level", "best_of", "round", "player_rank", "opponent_rank",
    "prior_matches_career", "surface_prior_matches", "player_cold_start",
    "sample_bucket_career", "ranking_bucket",
]


def _flatten_count_rows(count_rows: list[dict]) -> pd.DataFrame:
    flat = []
    for r in count_rows:
        td = r.get("train_dispersion") or {}
        base = {
            "tour": r["tour"], "fold": r["fold"], "market": r["market"],
            "variant": r["variant"], "window": r["window"],
            "train_mean": td.get("mean"), "train_var": td.get("var"),
            "train_dispersion_ratio": td.get("dispersion_ratio"),
            "train_overdispersed": td.get("overdispersed"),
            "threshold_train_median": r.get("threshold"), "negbin_r": r.get("r"),
        }
        pois = r.get("poisson") or {}
        for k, v in pois.items():
            base[f"poisson_{k}"] = v
        nb = r.get("negbin") or {}
        for k, v in nb.items():
            base[f"negbin_{k}"] = v
        flat.append(base)
    return pd.DataFrame(flat)


def _write_predictions(df: pd.DataFrame, tour: str) -> None:
    target_cols = [c for c in df.columns if c.startswith("target_")]
    pred_cols = [c for c in df.columns if c.startswith("pred_") or c.startswith("hist_mean_")]
    keep = [c for c in _KEEP_CONTEXT if c in df.columns] + target_cols + pred_cols
    for fold_name, train, test in iter_folds(df):
        out = test[keep].copy()
        out.insert(1, "fold", fold_name)
        out.to_parquet(PHASE4_PREDICTIONS_DIR / f"predictions_{tour}_{fold_name}.parquet", index=False)


def _summary_table(metrics_df: pd.DataFrame, prob_df: pd.DataFrame) -> pd.DataFrame:
    """Criterio de selecao do MELHOR baseline DENTRO de cada mercado: menor
    MAE medio bruto entre folds (comparacao justa, pois todas as variantes
    de um mesmo mercado preveem o MESMO alvo, na mesma escala -- nao precisa
    de normalizacao). Para a comparacao de previsibilidade ENTRE mercados
    (item 11, escalas diferentes: aces vs games vs sets), reportamos tambem
    `mae_relativo_ao_desvio` = MAE / desvio-padrao do alvo observado
    (equivalente a 1 menos uma nocao de R^2 -- comparavel entre mercados,
    e nao explode perto de 0 como MAE/media explodiria para `game_diff`,
    cuja media e proxima de 0 por construcao -- achado documentado no
    relatorio, nao um bug de calculo)."""

    rows = []
    overall_num = metrics_df[metrics_df["segment_type"] == "overall"].copy()
    overall_num = overall_num[overall_num["n"] > 0]
    overall_num["mae_rel_std"] = overall_num["mae"] / overall_num["actual_var"].pow(0.5).replace(0, np.nan)

    for tour in overall_num["tour"].unique():
        for market in overall_num["market"].unique():
            sub = overall_num[(overall_num["tour"] == tour) & (overall_num["market"] == market)]
            if sub.empty:
                continue
            by_variant_window = sub.groupby(["variant", "window"], as_index=False).agg(
                mean_mae=("mae", "mean"), mean_rmse=("rmse", "mean"),
                mean_mae_rel_std=("mae_rel_std", "mean"),
                std_mae=("mae", "std"), n_folds=("mae", "count"), mean_n=("n", "mean"),
            )
            by_variant_window = by_variant_window.dropna(subset=["mean_mae"])
            if by_variant_window.empty:
                continue
            best = by_variant_window.sort_values("mean_mae").iloc[0]
            rows.append({
                "tour": tour, "market": market,
                "melhor_baseline": f"{best['variant']}_{best['window']}",
                "criterio": "menor MAE bruto medio entre folds (mesma escala dentro do mercado)",
                "mae_medio": round(float(best["mean_mae"]), 4),
                "rmse_medio": round(float(best["mean_rmse"]), 4),
                "mae_relativo_ao_desvio": round(float(best["mean_mae_rel_std"]), 4) if pd.notna(best["mean_mae_rel_std"]) else None,
                "estabilidade_std_mae_entre_folds": round(float(best["std_mae"]), 4) if pd.notna(best["std_mae"]) else None,
                "cobertura_media_n_por_fold": round(float(best["mean_n"]), 1),
                "n_folds_com_dado": int(best["n_folds"]),
            })

    overall_prob = prob_df[prob_df["segment_type"] == "overall"].copy()
    overall_prob = overall_prob[overall_prob["n"] > 0]
    for tour in overall_prob["tour"].unique():
        for market in overall_prob["market"].unique():
            sub = overall_prob[(overall_prob["tour"] == tour) & (overall_prob["market"] == market)]
            if sub.empty:
                continue
            by_variant_window = sub.groupby(["variant", "window"], as_index=False).agg(
                mean_brier=("brier", "mean"), std_brier=("brier", "std"),
                mean_log_loss=("log_loss", "mean"), n_folds=("brier", "count"), mean_n=("n", "mean"),
            ).dropna(subset=["mean_brier"])
            if by_variant_window.empty:
                continue
            best = by_variant_window.sort_values("mean_brier").iloc[0]
            rows.append({
                "tour": tour, "market": market,
                "melhor_baseline": f"{best['variant']}_{best['window']}",
                "criterio": "menor Brier Score medio entre folds",
                "mae_medio": None, "rmse_medio": None,
                "brier_medio": round(float(best["mean_brier"]), 4),
                "log_loss_medio": round(float(best["mean_log_loss"]), 4) if pd.notna(best["mean_log_loss"]) else None,
                "estabilidade_std_brier_entre_folds": round(float(best["std_brier"]), 4) if pd.notna(best["std_brier"]) else None,
                "cobertura_media_n_por_fold": round(float(best["mean_n"]), 1),
                "n_folds_com_dado": int(best["n_folds"]),
            })

    return pd.DataFrame(rows)


def run() -> dict:
    PHASE4_PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
    PHASE4_METRICS_DIR.mkdir(parents=True, exist_ok=True)
    PHASE4_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    all_metrics, all_counts, all_probs = [], [], []
    diagnostics = {}
    for tour in TOURS:
        df = build_tour_table(tour)
        diagnostics[tour] = {
            "n_rows": len(df), "n_matches": int(df["match_id"].nunique()),
            "date_min": str(df["tournament_date"].min()), "date_max": str(df["tournament_date"].max()),
        }
        _write_predictions(df, tour)
        m_rows, c_rows = evaluate_numeric_markets(df, tour)
        p_rows = evaluate_prob_markets(df, tour)
        all_metrics += m_rows
        all_counts += c_rows
        all_probs += p_rows

    metrics_df = pd.DataFrame(all_metrics)
    counts_df = _flatten_count_rows(all_counts)
    prob_df = pd.DataFrame(all_probs)

    metrics_df.to_csv(PHASE4_METRICS_DIR / "numeric_metrics.csv", index=False)
    counts_df.to_csv(PHASE4_METRICS_DIR / "count_distribution_metrics.csv", index=False)
    prob_df.to_csv(PHASE4_METRICS_DIR / "probabilistic_metrics.csv", index=False)

    summary = _summary_table(metrics_df, prob_df)
    summary.to_csv(PHASE4_METRICS_DIR / "market_ranking_summary.csv", index=False)

    (PHASE4_CONFIG_DIR / "folds.json").write_text(json.dumps(FOLDS, indent=2), encoding="utf-8")
    (PHASE4_CONFIG_DIR / "phase4_diagnostics.json").write_text(json.dumps(diagnostics, indent=2, default=str), encoding="utf-8")

    return {
        "diagnostics": diagnostics,
        "n_numeric_metric_rows": len(metrics_df),
        "n_count_rows": len(counts_df),
        "n_prob_rows": len(prob_df),
        "n_summary_rows": len(summary),
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
