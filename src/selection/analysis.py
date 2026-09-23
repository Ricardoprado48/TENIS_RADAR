"""Fase 5 -- comparacao de robustez e selecao tecnica dos mercados.

Le SOMENTE os arquivos ja produzidos pela Fase 4 em
data/outputs/phase4/metrics/*.csv (numeric_metrics, probabilistic_metrics,
count_distribution_metrics). Nao treina, nao ajusta e nao recalcula nenhum
modelo -- apenas agrega e classifica resultados out-of-sample ja existentes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as cfg

NUMERIC_ERROR_COL = "mae"
PROB_ERROR_COL = "brier"


def load_metrics() -> dict[str, pd.DataFrame]:
    numeric = pd.read_csv(cfg.PHASE4_METRICS_DIR / "numeric_metrics.csv")
    prob = pd.read_csv(cfg.PHASE4_METRICS_DIR / "probabilistic_metrics.csv")
    count = pd.read_csv(cfg.PHASE4_METRICS_DIR / "count_distribution_metrics.csv")
    for df in (numeric, prob, count):
        for c in df.columns:
            if df[c].dtype == object or str(df[c].dtype) == "string":
                df[c] = df[c].astype(str)
    return {"numeric": numeric, "prob": prob, "count": count}


# --------------------------------------------------------------------------
# 1) robustez temporal (item 3): naive vs cada variante, fold a fold
# --------------------------------------------------------------------------

def _naive_key(kind: str) -> tuple[str, str]:
    return ("naive_train_mean", "none") if kind == "numeric" else ("naive_baserate", "none")


def temporal_robustness(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Para cada (tour, market, variant, window): erro por fold, erro do
    naive no mesmo fold, delta absoluto/relativo, contagem de vitorias."""
    error_col = NUMERIC_ERROR_COL if kind == "numeric" else PROB_ERROR_COL
    overall = df[df["segment_type"] == "overall"].copy()

    rows = []
    nv_variant, nv_window = _naive_key(kind)
    for (tour, market), g in overall.groupby(["tour", "market"]):
        naive_by_fold = (
            g[(g["variant"] == nv_variant) & (g["window"] == nv_window)]
            .set_index("fold")[error_col]
            .to_dict()
        )
        naive_n_by_fold = (
            g[(g["variant"] == nv_variant) & (g["window"] == nv_window)]
            .set_index("fold")["n"]
            .to_dict()
        )
        for (variant, window), gv in g.groupby(["variant", "window"]):
            if variant == nv_variant:
                continue
            per_fold = {}
            for _, r in gv.iterrows():
                fold = r["fold"]
                err = r[error_col]
                naive_err = naive_by_fold.get(fold)
                n = r["n"]
                naive_n = naive_n_by_fold.get(fold)
                if naive_err is None or pd.isna(err) or pd.isna(naive_err):
                    continue
                delta_abs = naive_err - err
                delta_rel = delta_abs / naive_err if naive_err else np.nan
                per_fold[fold] = {
                    "err": err, "naive_err": naive_err, "n": n, "naive_n": naive_n,
                    "delta_abs": delta_abs, "delta_rel": delta_rel,
                    "win": bool(delta_abs > 0),
                    "coverage_ok": bool(n is not None and n >= cfg.MIN_COVERAGE_N),
                }
            if not per_fold:
                continue
            wins = sum(1 for v in per_fold.values() if v["win"])
            strong_wins = sum(
                1 for v in per_fold.values()
                if v["win"] and v["delta_rel"] >= cfg.MIN_PER_FOLD_DELTA_REL_FOR_STRONG_WIN
            )
            deltas_rel = [v["delta_rel"] for v in per_fold.values()]
            coverage_ok_all = all(v["coverage_ok"] for v in per_fold.values())
            rows.append({
                "tour": tour, "market": market, "variant": variant, "window": window,
                "n_folds": len(per_fold), "wins": wins, "strong_wins": strong_wins,
                "mean_delta_abs": float(np.mean([v["delta_abs"] for v in per_fold.values()])),
                "mean_delta_rel": float(np.mean(deltas_rel)),
                "std_delta_rel": float(np.std(deltas_rel)),
                "min_delta_rel": float(np.min(deltas_rel)),
                "max_delta_rel": float(np.max(deltas_rel)),
                "coverage_ok_all_folds": coverage_ok_all,
                **{f"{fold}__err": v["err"] for fold, v in per_fold.items()},
                **{f"{fold}__naive_err": v["naive_err"] for fold, v in per_fold.items()},
                **{f"{fold}__delta_rel": v["delta_rel"] for fold, v in per_fold.items()},
                **{f"{fold}__win": v["win"] for fold, v in per_fold.items()},
                **{f"{fold}__n": v["n"] for fold, v in per_fold.items()},
            })
    return pd.DataFrame(rows)


def pick_best_approach(temporal_df: pd.DataFrame) -> pd.DataFrame:
    """Escolhe, por (tour, market), a variante+janela vencedora usando a
    regra objetiva: maior numero de folds vencidos primeiro, depois maior
    melhora relativa media, depois menor variabilidade entre folds."""
    if temporal_df.empty:
        return temporal_df
    df = temporal_df.copy()
    df = df.sort_values(
        by=["wins", "mean_delta_rel", "std_delta_rel"],
        ascending=[False, False, True],
    )
    best = df.groupby(["tour", "market"], as_index=False).first()
    return best


# --------------------------------------------------------------------------
# 2) robustez por superficie (item 4)
# --------------------------------------------------------------------------

def surface_robustness(df: pd.DataFrame, kind: str, best: pd.DataFrame) -> pd.DataFrame:
    error_col = NUMERIC_ERROR_COL if kind == "numeric" else PROB_ERROR_COL
    surf = df[df["segment_type"] == "surface"].copy()
    nv_variant, nv_window = _naive_key(kind)

    rows = []
    for _, b in best.iterrows():
        tour, market, variant, window = b["tour"], b["market"], b["variant"], b["window"]
        sub_model = surf[
            (surf["tour"] == tour) & (surf["market"] == market)
            & (surf["variant"] == variant) & (surf["window"] == window)
        ]
        sub_naive = surf[
            (surf["tour"] == tour) & (surf["market"] == market)
            & (surf["variant"] == nv_variant) & (surf["window"] == nv_window)
        ]
        for surface in ["Hard", "Clay", "Grass"]:
            m = sub_model[sub_model["segment_value"] == surface]
            nv = sub_naive[sub_naive["segment_value"] == surface]
            if m.empty or nv.empty:
                continue
            model_err = m[error_col].mean()
            naive_err = nv[error_col].mean()
            n_total = int(m["n"].sum())
            if pd.isna(model_err) or pd.isna(naive_err) or naive_err == 0:
                continue
            delta_rel = (naive_err - model_err) / naive_err
            flagged = bool(
                n_total >= cfg.MIN_SURFACE_N_FOR_FLAG
                and delta_rel < -cfg.MAX_SURFACE_DETERIORATION_REL
            )
            rows.append({
                "tour": tour, "market": market, "variant": variant, "window": window,
                "surface": surface, "n_total": n_total,
                "model_err_mean": model_err, "naive_err_mean": naive_err,
                "delta_rel": delta_rel, "deterioration_flagged": flagged,
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 3) robustez de janela (item 6)
# --------------------------------------------------------------------------

def window_robustness(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Para cada (tour, market, variant) com mais de uma janela: media e
    desvio-padrao do erro entre folds (estabilidade temporal) e entre
    superficies (estabilidade por superficie), por janela."""
    error_col = NUMERIC_ERROR_COL if kind == "numeric" else PROB_ERROR_COL
    overall = df[df["segment_type"] == "overall"].copy()
    surf = df[df["segment_type"] == "surface"].copy()

    rows = []
    for (tour, market, variant), g in overall.groupby(["tour", "market", "variant"]):
        windows = g["window"].unique()
        if len(windows) <= 1:
            continue
        for window in windows:
            gw = g[g["window"] == window]
            temporal_vals = gw[error_col].dropna().to_numpy()
            if len(temporal_vals) == 0:
                continue
            sw = surf[
                (surf["tour"] == tour) & (surf["market"] == market)
                & (surf["variant"] == variant) & (surf["window"] == window)
            ]
            surface_vals = sw.groupby("segment_value")[error_col].mean().dropna().to_numpy()
            rows.append({
                "tour": tour, "market": market, "variant": variant, "window": window,
                "mean_err_temporal": float(np.mean(temporal_vals)),
                "std_err_temporal": float(np.std(temporal_vals)),
                "mean_err_surface": float(np.mean(surface_vals)) if len(surface_vals) else np.nan,
                "std_err_surface": float(np.std(surface_vals)) if len(surface_vals) else np.nan,
            })
    out = pd.DataFrame(rows)
    if out.empty:
        return out

    ranked_parts = []
    for _, g in out.groupby(["tour", "market", "variant"]):
        g = g.copy()
        g["rank_mean"] = g["mean_err_temporal"].rank(method="min")
        g["rank_std_temporal"] = g["std_err_temporal"].rank(method="min")
        g["rank_std_surface"] = g["std_err_surface"].rank(method="min")
        g["rank_sum"] = (
            g["rank_mean"] + g["rank_std_temporal"]
            + g["rank_std_surface"].fillna(g["rank_std_surface"].max())
        )
        ranked_parts.append(g)
    out = pd.concat(ranked_parts, ignore_index=True)
    return out.sort_values(["tour", "market", "variant", "rank_sum"])


def best_window_per_group(window_df: pd.DataFrame) -> pd.DataFrame:
    if window_df.empty:
        return window_df
    idx = window_df.groupby(["tour", "market", "variant"])["rank_sum"].idxmin()
    return window_df.loc[idx].sort_values(["tour", "market", "variant"])


# --------------------------------------------------------------------------
# 4) Serve x Return (aces) e Hold x Break (games) -- item 5
# --------------------------------------------------------------------------

def variant_ladder_at_window(
    df: pd.DataFrame, kind: str, markets: list[str], window: str,
    variants_order: list[str],
) -> pd.DataFrame:
    """Compara, numa janela fixa comum, naive -> isolated -> matchup ->
    oppadj (quando existirem), por fold e por superficie, para os mercados
    dados. Usado tanto para aces (Serve x Return) quanto para games
    (Hold x Break)."""
    error_col = NUMERIC_ERROR_COL if kind == "numeric" else PROB_ERROR_COL
    nv_variant, nv_window = _naive_key(kind)

    overall = df[(df["segment_type"] == "overall") & (df["market"].isin(markets))].copy()
    surf = df[(df["segment_type"] == "surface") & (df["market"].isin(markets))].copy()

    rows = []
    for (tour, market), g in overall.groupby(["tour", "market"]):
        naive_rows = g[(g["variant"] == nv_variant) & (g["window"] == nv_window)]
        for fold in cfg.FOLDS:
            naive_r = naive_rows[naive_rows["fold"] == fold]
            naive_err = naive_r[error_col].iloc[0] if len(naive_r) else np.nan
            for variant in variants_order:
                r = g[(g["variant"] == variant) & (g["window"] == window) & (g["fold"] == fold)]
                if r.empty:
                    continue
                err = r[error_col].iloc[0]
                n = r["n"].iloc[0]
                rows.append({
                    "tour": tour, "market": market, "fold": fold, "segment": "overall",
                    "variant": variant, "window": window, "n": n, "err": err,
                    "naive_err": naive_err,
                    "delta_rel_vs_naive": (naive_err - err) / naive_err if naive_err else np.nan,
                })
        for surface in ["Hard", "Clay", "Grass"]:
            sg = surf[(surf["tour"] == tour) & (surf["market"] == market) & (surf["segment_value"] == surface)]
            naive_sg = sg[(sg["variant"] == nv_variant) & (sg["window"] == nv_window)]
            naive_err_s = naive_sg[error_col].mean() if len(naive_sg) else np.nan
            for variant in variants_order:
                vs = sg[(sg["variant"] == variant) & (sg["window"] == window)]
                if vs.empty:
                    continue
                err = vs[error_col].mean()
                n = int(vs["n"].sum())
                rows.append({
                    "tour": tour, "market": market, "fold": "all_folds_mean", "segment": surface,
                    "variant": variant, "window": window, "n": n, "err": err,
                    "naive_err": naive_err_s,
                    "delta_rel_vs_naive": (naive_err_s - err) / naive_err_s if naive_err_s else np.nan,
                })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 5) overdispersion (item 7)
# --------------------------------------------------------------------------

def overdispersion_table(count_df: pd.DataFrame) -> pd.DataFrame:
    df = count_df.copy()
    df["negbin_wins"] = df["negbin_brier"] < df["poisson_brier"]
    keep = [
        "tour", "fold", "market", "variant", "window",
        "train_mean", "train_var", "train_dispersion_ratio", "train_overdispersed",
        "negbin_r", "poisson_brier", "negbin_brier", "negbin_wins",
    ]
    return df[keep].sort_values(["tour", "market", "variant", "window", "fold"])


def overdispersion_summary(count_df: pd.DataFrame) -> pd.DataFrame:
    df = count_df.copy()
    df["negbin_wins"] = (df["negbin_brier"] < df["poisson_brier"]).astype(int)
    df["has_negbin"] = df["negbin_r"].notna().astype(int)
    g = df.groupby(["tour", "market"]).agg(
        n_rows=("negbin_wins", "size"),
        negbin_win_rate=("negbin_wins", "mean"),
        pct_folds_overdispersed=("train_overdispersed", "mean"),
        mean_dispersion_ratio=("train_dispersion_ratio", "mean"),
        pct_negbin_fit=("has_negbin", "mean"),
        mean_poisson_brier=("poisson_brier", "mean"),
        mean_negbin_brier=("negbin_brier", "mean"),
    ).reset_index()
    return g
