"""Orquestrador da Fase 6.1: calibra a probabilidade Negative Binomial da
Fase 6 (`p_over_negbin`) com Platt scaling e Isotonic regression, usando
SOMENTE dados de folds temporalmente anteriores para ajustar cada
calibrador (item 3). Nao altera os modelos de contagem da Fase 6 -- so
consome `p_over_negbin` e `actual_over` ja calculados la.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import config as cfg
from . import diagnostics as diag
from . import evaluate as ev
from . import methods as meth
from . import selection as sel

_OUTPUT_COLS = [
    "tour", "market", "fold", "surface", "match_id", "player_id", "line",
    "sample_bucket_career", "raw_probability", "platt_probability",
    "isotonic_probability", "calibrated_probability", "method_selected",
    "calibrator_train_n",
]


def load_data() -> pd.DataFrame:
    df = pd.read_parquet(cfg.PHASE6_PREDICTIONS_PATH)
    df = df[df["market"].isin(cfg.MARKETS)]
    df = df[df[cfg.RAW_PROB_COL].notna() & df[cfg.ACTUAL_COL].notna()]
    return df


def _apply_calibration_for_tour_market(sub: pd.DataFrame) -> pd.DataFrame:
    """Retorna sub com raw/platt/isotonic_probability preenchidos para
    fold_2024 (passthrough, sem calibrador -- item 3) e para os folds
    avaliaveis (calibrador ajustado so com folds ANTERIORES)."""

    parts = []

    f24 = sub[sub["fold"].isin(cfg.NO_PRIOR_PERIOD_FOLDS)].copy()
    if not f24.empty:
        f24["raw_probability"] = f24[cfg.RAW_PROB_COL]
        f24["platt_probability"] = np.nan
        f24["isotonic_probability"] = np.nan
        f24["calibrator_train_n"] = 0
        parts.append(f24)

    for eval_fold, train_folds in cfg.CALIBRATION_TRAIN_FOLDS.items():
        train_df = sub[sub["fold"].isin(train_folds)]
        test_df = sub[sub["fold"] == eval_fold].copy()
        if test_df.empty:
            continue
        p_train = train_df[cfg.RAW_PROB_COL].to_numpy(dtype="float64")
        y_train = train_df[cfg.ACTUAL_COL].to_numpy(dtype="float64")
        n_train = len(train_df)

        platt_model, _ = meth.fit_calibrator("platt", p_train, y_train)
        iso_model, _ = meth.fit_calibrator("isotonic", p_train, y_train)

        p_test = test_df[cfg.RAW_PROB_COL].to_numpy(dtype="float64")
        test_df["raw_probability"] = p_test
        test_df["platt_probability"] = platt_model.predict(p_test)
        test_df["isotonic_probability"] = iso_model.predict(p_test)
        test_df["calibrator_train_n"] = n_train
        parts.append(test_df)

    return pd.concat(parts, ignore_index=True) if parts else sub.iloc[0:0]


def run() -> dict:
    cfg.PHASE6_1_DIR.mkdir(parents=True, exist_ok=True)
    df = load_data()

    calibrated_parts = []
    metrics_parts = []
    reliability_parts = []
    difficulty_parts = []
    surface_parts = []
    selection_rows = []
    surface_decision_rows = []

    method_cols = {"raw": "raw_probability", "platt": "platt_probability", "isotonic": "isotonic_probability"}

    for tour in cfg.TOURS:
        for market in cfg.MARKETS:
            sub = df[(df["tour"] == tour) & (df["market"] == market)]
            if sub.empty:
                continue
            calibrated = _apply_calibration_for_tour_market(sub)
            calibrated_parts.append(calibrated)

            evaluable = calibrated[calibrated["fold"].isin(cfg.EVALUABLE_FOLDS)]

            m = ev.metrics_by_group(evaluable, cfg.ACTUAL_COL, method_cols, ["tour", "market", "fold"])
            metrics_parts.append(m)

            for method, col in method_cols.items():
                rel = ev.reliability_by_bucket(evaluable, cfg.ACTUAL_COL, col, ["tour", "market", "fold"])
                rel["method"] = method
                reliability_parts.append(rel)

            diffm = ev.metrics_by_group(evaluable, cfg.ACTUAL_COL, method_cols, ["tour", "market", "line_difficulty"])
            difficulty_parts.append(diffm)

            surf_m = ev.metrics_by_group(evaluable, cfg.ACTUAL_COL, method_cols, ["tour", "market", "surface"])
            surface_parts.append(surf_m)

            # --- selecao do metodo (item 9) ---
            decision = sel.select_method(m, tour, market)
            selection_rows.append({k: v for k, v in decision.items() if k != "detalhe"})
            chosen = decision["method_selected"]
            chosen_col = method_cols[chosen]
            calibrated["method_selected"] = np.where(
                calibrated["fold"].isin(cfg.NO_PRIOR_PERIOD_FOLDS), "raw_sem_periodo_anterior", chosen,
            )
            calibrated["calibrated_probability"] = np.where(
                calibrated["fold"].isin(cfg.NO_PRIOR_PERIOD_FOLDS),
                calibrated["raw_probability"],
                calibrated[chosen_col],
            )

            # --- item 7: calibrador global vs especifico de Grass ---
            for eval_fold, train_folds in cfg.CALIBRATION_TRAIN_FOLDS.items():
                train_grass = sub[sub["fold"].isin(train_folds) & (sub["surface"] == "Grass")]
                test_grass = sub[(sub["fold"] == eval_fold) & (sub["surface"] == "Grass")]
                if test_grass.empty:
                    continue
                # desempenho do calibrador GLOBAL (ja aplicado acima) restrito a Grass
                global_test = calibrated[(calibrated["fold"] == eval_fold) & (calibrated["surface"] == "Grass")]
                brier_global = float(((global_test[chosen_col] - global_test[cfg.ACTUAL_COL]) ** 2).mean()) if not global_test.empty else None

                n_train_grass = len(train_grass)
                brier_specific = None
                if chosen == "raw":
                    status_specific = "nao_aplicavel_raw_foi_o_metodo_escolhido"
                elif n_train_grass < cfg.MIN_CALIBRATOR_TRAIN_N:
                    status_specific = "amostra_insuficiente"
                else:
                    status_specific = None
                if n_train_grass >= cfg.MIN_CALIBRATOR_TRAIN_N and chosen != "raw":
                    model_g, status_specific = meth.fit_calibrator(
                        chosen, train_grass[cfg.RAW_PROB_COL].to_numpy(dtype="float64"),
                        train_grass[cfg.ACTUAL_COL].to_numpy(dtype="float64"),
                    )
                    p_specific = model_g.predict(test_grass[cfg.RAW_PROB_COL].to_numpy(dtype="float64"))
                    brier_specific = float(((p_specific - test_grass[cfg.ACTUAL_COL].to_numpy()) ** 2).mean())

                surface_decision_rows.append({
                    "tour": tour, "market": market, "fold": eval_fold,
                    "metodo_escolhido_global": chosen,
                    "n_treino_grass": n_train_grass, "n_teste_grass": len(test_grass),
                    "brier_calibrador_global_em_grass": brier_global,
                    "brier_calibrador_especifico_grass": brier_specific,
                    "status_calibrador_especifico": status_specific,
                })

    calibrated_all = pd.concat(calibrated_parts, ignore_index=True)
    calibrated_all[_OUTPUT_COLS].to_parquet(cfg.PHASE6_1_DIR / "previsoes_calibradas.parquet", index=False)

    pd.concat(metrics_parts, ignore_index=True).to_csv(cfg.PHASE6_1_DIR / "metricas_antes_depois.csv", index=False)
    pd.concat(reliability_parts, ignore_index=True).to_csv(cfg.PHASE6_1_DIR / "reliability_por_bucket.csv", index=False)
    pd.concat(difficulty_parts, ignore_index=True).to_csv(cfg.PHASE6_1_DIR / "metricas_por_dificuldade_linha.csv", index=False)
    pd.concat(surface_parts, ignore_index=True).to_csv(cfg.PHASE6_1_DIR / "metricas_por_superficie.csv", index=False)
    pd.DataFrame(selection_rows).to_csv(cfg.PHASE6_1_DIR / "selecao_metodo_por_mercado.csv", index=False)
    pd.DataFrame(surface_decision_rows).to_csv(cfg.PHASE6_1_DIR / "calibrador_superficie_grass.csv", index=False)

    # --- item 10: diagnostico NegBin vs Poisson (independente de calibracao) ---
    diag_overall = diag.negbin_vs_poisson_diagnostics(df, ["tour", "market"])
    diag_overall.to_csv(cfg.PHASE6_1_DIR / "diagnostico_negbin_vs_poisson.csv", index=False)
    diag_by_difficulty = diag.negbin_vs_poisson_diagnostics(df, ["tour", "market", "line_difficulty"])
    diag_by_difficulty.to_csv(cfg.PHASE6_1_DIR / "diagnostico_negbin_vs_poisson_por_dificuldade.csv", index=False)

    summary = {
        "n_rows_total": int(len(calibrated_all)),
        "n_rows_evaluable": int(len(calibrated_all[calibrated_all["fold"].isin(cfg.EVALUABLE_FOLDS)])),
        "selection": selection_rows,
    }
    with open(cfg.PHASE6_1_DIR / "phase6_1_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    return summary
