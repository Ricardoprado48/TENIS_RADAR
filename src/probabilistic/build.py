"""Orquestrador da Fase 6: transforma as previsoes pontuais e os parametros
de dispersao ja produzidos na Fase 4 em distribuicoes de probabilidade por
linha .5, avalia calibracao fora da amostra, e grava tudo em
data/outputs/phase6/.

Nao le data/processed/ nem data/raw/. Nao ajusta nenhum parametro novo: lambda
vem das colunas pred_* da Fase 4; `r` (Negative Binomial) vem de negbin_r em
count_distribution_metrics.csv (ajustado so no treino, na Fase 4).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import calibration as cal
from . import config as cfg
from . import dependency as dep
from . import distributions as dist
from . import selection as sel

_KEEP_CONTEXT = [
    "match_id", "player_id", "opponent_id", "tournament_date", "surface",
    "player_rank", "opponent_rank", "prior_matches_career", "sample_bucket_career",
    "ranking_bucket",
]


def _load_predictions(tour: str) -> dict[str, pd.DataFrame]:
    return {
        fold: pd.read_parquet(cfg.PHASE4_PREDICTIONS_DIR / f"predictions_{tour}_{fold}.parquet")
        for fold in cfg.FOLDS
    }


def _cd_lookup(cd_df: pd.DataFrame, tour: str, fold: str, market: str, variant: str, window: str) -> dict:
    sub = cd_df[(cd_df["tour"] == tour) & (cd_df["fold"] == fold) & (cd_df["market"] == market)
                & (cd_df["variant"] == variant) & (cd_df["window"] == window)]
    if sub.empty:
        return {"train_mean": None, "negbin_r": None}
    row = sub.iloc[0]
    r = row["negbin_r"]
    return {"train_mean": float(row["train_mean"]) if pd.notna(row["train_mean"]) else None,
            "negbin_r": float(r) if pd.notna(r) else None}


def _rows_for_config(test_df: pd.DataFrame, tour: str, fold: str, market: str,
                      mc: sel.MarketConfig, cd_df: pd.DataFrame) -> list[pd.DataFrame]:
    actual_col = cfg.ACTUAL_COL[market]

    base_info = _cd_lookup(cd_df, tour, fold, market, mc.base_variant, mc.base_window)
    grass_info = _cd_lookup(cd_df, tour, fold, market, mc.grass_variant, mc.grass_window)

    # grade de linhas comum ao mercado/tour/fold inteiro, derivada da
    # distribuicao BASE (item 5) -- assim "Over 6.5" significa a mesma coisa
    # em todas as superficies do mesmo tour/fold/mercado.
    lines = dist.generate_line_grid(base_info["train_mean"], base_info["negbin_r"])
    if not lines:
        return []

    out_parts = []
    for surface_mask, variant, window, r_use in [
        (test_df["surface"] != "Grass", mc.base_variant, mc.base_window, base_info["negbin_r"]),
        (test_df["surface"] == "Grass", mc.grass_variant, mc.grass_window, grass_info["negbin_r"]),
    ]:
        pred_col = cfg.pred_column_name(market, variant, window)
        if pred_col not in test_df.columns:
            continue
        sub = test_df.loc[surface_mask]
        lam_all = pd.to_numeric(sub[pred_col], errors="coerce").to_numpy(dtype="float64")
        actual_all = pd.to_numeric(sub[actual_col], errors="coerce").to_numpy(dtype="float64")
        valid = np.isfinite(lam_all) & (lam_all > 0) & np.isfinite(actual_all)
        if valid.sum() == 0:
            continue
        ctx = sub.loc[valid, [c for c in _KEEP_CONTEXT if c in sub.columns]].reset_index(drop=True)
        lam = lam_all[valid]
        actual = actual_all[valid]

        for line in lines:
            probs = dist.line_probabilities(lam, r_use, line)
            diff_bucket = dist.line_difficulty_bucket(line, lam, r_use)
            part = ctx.copy()
            part["tour"] = tour
            part["fold"] = fold
            part["market"] = market
            part["config_variant"] = variant
            part["config_window"] = window
            part["lambda"] = lam
            part["negbin_r"] = r_use if r_use is not None else np.nan
            part["line"] = line
            part["actual"] = actual
            part["actual_over"] = (actual > line).astype("float64")
            part["line_difficulty"] = diff_bucket
            part["p_over_poisson"] = probs["p_over_poisson"]
            part["p_under_poisson"] = probs["p_under_poisson"]
            part["p_over_negbin"] = probs["p_over_negbin"]
            part["p_under_negbin"] = probs["p_under_negbin"]
            out_parts.append(part)
    return out_parts


def build_predictions_by_line(configs: list[sel.MarketConfig], cd_df: pd.DataFrame) -> pd.DataFrame:
    all_parts = []
    for tour in cfg.TOURS:
        preds = _load_predictions(tour)
        tour_configs = [c for c in configs if c.tour == tour]
        for fold, test_df in preds.items():
            for mc in tour_configs:
                all_parts += _rows_for_config(test_df, tour, fold, mc.market, mc, cd_df)
    if not all_parts:
        return pd.DataFrame()
    return pd.concat(all_parts, ignore_index=True)


def _poisson_vs_negbin_winrate(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    d = df.dropna(subset=["p_over_negbin"]).copy()
    if d.empty:
        return pd.DataFrame()
    d["sq_err_poisson"] = (d["p_over_poisson"] - d["actual_over"]) ** 2
    d["sq_err_negbin"] = (d["p_over_negbin"] - d["actual_over"]) ** 2
    d["negbin_wins"] = d["sq_err_negbin"] < d["sq_err_poisson"]
    rows = []
    for key, sub in d.groupby(group_cols, dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        row = dict(zip(group_cols, key))
        row.update({
            "n": len(sub),
            "brier_poisson": float(sub["sq_err_poisson"].mean()),
            "brier_negbin": float(sub["sq_err_negbin"].mean()),
            "pct_negbin_wins": float(sub["negbin_wins"].mean()),
        })
        rows.append(row)
    return pd.DataFrame(rows)


def build_dependency_report(configs: list[sel.MarketConfig], cd_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    corr_rows = []
    line_rows = []
    for tour in cfg.TOURS:
        preds = _load_predictions(tour)
        aces_cfg = next(c for c in configs if c.tour == tour and c.market == "aces_player")
        total_cfg = next(c for c in configs if c.tour == tour and c.market == "total_aces_match")

        for fold, test_df in preds.items():
            corr = dep.residual_correlation(test_df)
            corr_rows.append({"tour": tour, "fold": fold, **corr})

            aces_pred_col = cfg.pred_column_name("aces_player", aces_cfg.base_variant, aces_cfg.base_window)
            total_pred_col = cfg.pred_column_name("total_aces_match", total_cfg.base_variant, total_cfg.base_window)
            if aces_pred_col not in test_df.columns or total_pred_col not in test_df.columns:
                continue

            aces_info = _cd_lookup(cd_df, tour, fold, "aces_player", aces_cfg.base_variant, aces_cfg.base_window)
            total_info = _cd_lookup(cd_df, tour, fold, "total_aces_match", total_cfg.base_variant, total_cfg.base_window)
            non_grass = test_df.loc[test_df["surface"] != "Grass"]
            result = dep.compare_independence_vs_empirical(
                non_grass, total_pred_col, total_info["negbin_r"], total_info["train_mean"],
                aces_pred_col, aces_info["negbin_r"],
            )
            for r in result["lines"]:
                line_rows.append({"tour": tour, "fold": fold, **r})
    return pd.DataFrame(corr_rows), pd.DataFrame(line_rows)


def run() -> dict:
    cfg.PHASE6_DIR.mkdir(parents=True, exist_ok=True)

    configs = sel.build_all_configs()
    configs_df = sel.configs_to_frame(configs)
    configs_df.to_csv(cfg.PHASE6_DIR / "configuracao_por_mercado.csv", index=False)

    cd_df = pd.read_csv(cfg.PHASE4_METRICS_DIR / "count_distribution_metrics.csv")

    by_line = build_predictions_by_line(configs, cd_df)
    by_line.to_parquet(cfg.PHASE6_DIR / "previsoes_por_linha.parquet", index=False)

    examples = by_line[by_line["market"] != "double_faults_player"].copy()
    if not examples.empty:
        sample_matches = (
            examples[["tour", "match_id"]].drop_duplicates().sample(
                n=min(8, examples["match_id"].nunique()), random_state=cfg.RANDOM_SEED
            )
        )
        examples = examples.merge(sample_matches, on=["tour", "match_id"])
        examples.to_csv(cfg.PHASE6_DIR / "exemplos_previsoes.csv", index=False)

    # --- calibracao geral (Negative Binomial, a distribuicao priorizada) ---
    nb = by_line.dropna(subset=["p_over_negbin"]).rename(columns={"p_over_negbin": "p_over"})
    if not nb.empty:
        cal.segment_metrics(nb, "actual_over", "p_over", ["tour", "market"]).to_csv(
            cfg.PHASE6_DIR / "calibracao_por_mercado.csv", index=False)
        cal.segment_metrics(nb, "actual_over", "p_over", ["tour", "market", "fold"]).to_csv(
            cfg.PHASE6_DIR / "calibracao_por_fold.csv", index=False)
        cal.segment_metrics(nb, "actual_over", "p_over", ["tour", "market", "surface"]).to_csv(
            cfg.PHASE6_DIR / "calibracao_por_superficie.csv", index=False)
        cal.segment_metrics(nb, "actual_over", "p_over", ["tour", "market", "sample_bucket_career"]).to_csv(
            cfg.PHASE6_DIR / "calibracao_por_historico.csv", index=False)
        cal.segment_metrics(nb, "actual_over", "p_over", ["tour", "market", "line_difficulty"]).to_csv(
            cfg.PHASE6_DIR / "calibracao_por_dificuldade_linha.csv", index=False)
        cal.reliability_table(nb, "actual_over", "p_over", group_cols=["tour", "market"]).to_csv(
            cfg.PHASE6_DIR / "reliability_curve.csv", index=False)

    # --- Poisson vs Negative Binomial ---
    pvn_overall = _poisson_vs_negbin_winrate(by_line, ["tour", "market"])
    pvn_overall.to_csv(cfg.PHASE6_DIR / "poisson_vs_negbin.csv", index=False)
    pvn_by_fold = _poisson_vs_negbin_winrate(by_line, ["tour", "market", "fold"])
    pvn_by_fold.to_csv(cfg.PHASE6_DIR / "poisson_vs_negbin_por_fold.csv", index=False)
    pvn_by_surface = _poisson_vs_negbin_winrate(by_line, ["tour", "market", "surface"])
    pvn_by_surface.to_csv(cfg.PHASE6_DIR / "poisson_vs_negbin_por_superficie.csv", index=False)

    # --- total de aces: independencia vs ajuste empirico ---
    corr_df, dep_lines_df = build_dependency_report(configs, cd_df)
    corr_df.to_csv(cfg.PHASE6_DIR / "total_aces_correlacao_residual.csv", index=False)
    dep_lines_df.to_csv(cfg.PHASE6_DIR / "total_aces_independencia_vs_empirico.csv", index=False)

    dep_summary_rows = []
    if not dep_lines_df.empty:
        for tour, sub in dep_lines_df.groupby("tour"):
            sub_valid = sub.dropna(subset=["brier_independente", "brier_empirico"])
            if sub_valid.empty:
                continue
            mean_a = float(sub_valid["brier_independente"].mean())
            mean_b = float(sub_valid["brier_empirico"].mean())
            rel_gain = (mean_a - mean_b) / mean_a if mean_a > 0 else 0.0
            decision = "empirico" if rel_gain >= cfg.MIN_BRIER_GAIN_REL_FOR_DEPENDENCY_ADJUSTMENT else "independente (mais simples)"
            dep_summary_rows.append({
                "tour": tour, "brier_medio_independente": round(mean_a, 5),
                "brier_medio_empirico": round(mean_b, 5),
                "ganho_relativo_empirico": round(rel_gain, 5),
                "decisao": decision,
            })
    dep_summary_df = pd.DataFrame(dep_summary_rows)
    dep_summary_df.to_csv(cfg.PHASE6_DIR / "total_aces_decisao_dependencia.csv", index=False)

    summary = {
        "n_configs": len(configs_df),
        "n_predictions_by_line_rows": int(len(by_line)),
        "n_markets": len(cfg.MARKETS),
        "dependency_decisions": dep_summary_df.to_dict(orient="records"),
    }
    with open(cfg.PHASE6_DIR / "phase6_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    return summary
