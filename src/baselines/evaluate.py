"""Orquestrador da avaliacao walk-forward (Fase 4). Monta a tabela completa
de previsoes por tour (features da Fase 3 + targets + baselines), particiona
em folds cronologicos, e calcula metricas por mercado x variante (isolado /
matchup / opponent-adjusted / media historica) x janela x segmento.

NENHUM parametro e ajustado usando dado do fold de teste: os unicos
"parametros ajustados" de toda a Fase 4 sao a dispersao Negative Binomial
(count_dist.py) e os coeficientes da regressao logistica de tie-break
(tiebreak_model.py) -- ambos, por construcao, so recebem `train_df`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.config import FEATURES_TOUR_DIRS, HEADLINE_WINDOWS
from src.features.profile import ALL_WINDOW_NAMES
from src.normalization.config import TOURS

from .count_dist import evaluate_count_market
from .games_model import _ADJUSTMENT_WINDOWS as GAMES_ADJ_WINDOWS
from .games_model import add_games_predictions
from .history_means import build_history_mean_priors
from .metrics import brier_score, calibration_error, numeric_metrics
from .rate_models import _ADJUSTMENT_WINDOWS as ACE_ADJ_WINDOWS
from .rate_models import add_ace_predictions, add_double_fault_predictions, add_total_aces_predictions
from .targets import attach_targets
from .tiebreak_model import fit_and_predict_tiebreak_logit
from .walkforward import iter_folds, ranking_bucket, sample_size_bucket


def build_tour_table(tour: str) -> pd.DataFrame:
    path = FEATURES_TOUR_DIRS[tour] / "player_match_features.parquet"
    features = pd.read_parquet(path)
    assert features["tournament_date"].is_monotonic_increasing, (
        "player_match_features.parquet nao esta em ordem cronologica -- "
        "as agregacoes point-in-time desta fase dependem dessa ordem."
    )
    df = attach_targets(features, tour)
    df["tour"] = tour.upper()

    hist = build_history_mean_priors(df)
    df = pd.concat([df, hist], axis=1)

    df = add_ace_predictions(df)
    df = add_double_fault_predictions(df)
    df = add_total_aces_predictions(df)
    df = add_games_predictions(df)

    df["sample_bucket_career"] = sample_size_bucket(df["prior_matches_career"])
    df["ranking_bucket"] = ranking_bucket(df["player_rank"])
    return df


def _segments(df: pd.DataFrame) -> dict:
    segs = {("overall", "overall"): pd.Series(True, index=df.index)}
    for s in ["Hard", "Clay", "Grass"]:
        segs[("surface", s)] = (df["surface"] == s)
    for b in df["sample_bucket_career"].dropna().unique():
        segs[("sample_bucket", b)] = (df["sample_bucket_career"] == b)
    for b in df["ranking_bucket"].dropna().unique():
        segs[("ranking_bucket", b)] = (df["ranking_bucket"] == b)
    return segs


def _variant_cols(prefix: str, window_sets: dict) -> list[tuple[str, str, str]]:
    out = []
    for variant, windows in window_sets.items():
        for w in windows:
            col = f"{prefix}_{variant}_{w}"
            out.append((variant, w, col))
    return out


# --------------------------------------------------------------------------
# definicao dos mercados: (nome, kind, actual_col, lista de (variant, window, pred_col))
# --------------------------------------------------------------------------

def _numeric_market_specs(df_cols) -> dict:
    specs = {}

    aces_variants = _variant_cols("pred_aces", {
        "isolated": ALL_WINDOW_NAMES, "matchup": HEADLINE_WINDOWS, "oppadj": ACE_ADJ_WINDOWS,
    })
    aces_variants += [("history_mean", w, f"hist_mean_aces_{w}") for w in ALL_WINDOW_NAMES]
    specs["aces_player"] = {"actual": "target_aces", "cols": aces_variants, "filter": None}

    total_aces_variants = _variant_cols("pred_total_aces", {
        "isolated": ALL_WINDOW_NAMES, "matchup": HEADLINE_WINDOWS, "oppadj": ACE_ADJ_WINDOWS,
    })
    total_aces_variants += [("history_mean", w, f"hist_mean_total_aces_match_{w}") for w in ALL_WINDOW_NAMES]
    specs["total_aces_match"] = {"actual": "target_total_aces_match", "cols": total_aces_variants, "filter": None}

    df_variants = [("isolated", w, f"pred_double_faults_{w}") for w in ALL_WINDOW_NAMES]
    df_variants += [("history_mean", w, f"hist_mean_double_faults_{w}") for w in ALL_WINDOW_NAMES]
    specs["double_faults_player"] = {"actual": "target_double_faults", "cols": df_variants, "filter": None}

    complete_filter = "target_score_complete"

    games_variants = _variant_cols("pred_total_games", {
        "isolated": HEADLINE_WINDOWS, "matchup": HEADLINE_WINDOWS, "oppadj": GAMES_ADJ_WINDOWS,
    })
    games_variants += [("history_mean", w, f"hist_mean_total_games_{w}") for w in ALL_WINDOW_NAMES]
    specs["total_games"] = {"actual": "target_total_games", "cols": games_variants, "filter": complete_filter}

    diff_variants = _variant_cols("pred_game_diff", {
        "isolated": HEADLINE_WINDOWS, "matchup": HEADLINE_WINDOWS, "oppadj": GAMES_ADJ_WINDOWS,
    })
    diff_variants += [("history_mean", w, f"hist_mean_game_diff_{w}") for w in ALL_WINDOW_NAMES]
    specs["game_diff"] = {"actual": "target_game_diff", "cols": diff_variants, "filter": complete_filter}

    sets_variants = _variant_cols("pred_n_sets", {
        "isolated": HEADLINE_WINDOWS, "matchup": HEADLINE_WINDOWS, "oppadj": GAMES_ADJ_WINDOWS,
    })
    specs["total_sets"] = {"actual": "target_total_sets", "cols": sets_variants, "filter": complete_filter}

    return specs


def _count_market_keys() -> list[str]:
    return ["aces_player", "total_aces_match", "double_faults_player"]


def _prob_market_specs() -> dict:
    specs = {}
    tb_variants = _variant_cols("pred_p_tiebreak", {
        "isolated": HEADLINE_WINDOWS, "matchup": HEADLINE_WINDOWS, "oppadj": GAMES_ADJ_WINDOWS,
    })
    tb_variants += [("history_mean_rate", w, f"hist_mean_has_tiebreak_{w}") for w in ALL_WINDOW_NAMES]
    specs["tiebreak"] = {"actual": "target_has_tiebreak", "cols": tb_variants, "filter": "target_score_complete"}

    fd_variants = _variant_cols("pred_p_full_distance", {
        "isolated": HEADLINE_WINDOWS, "matchup": HEADLINE_WINDOWS, "oppadj": GAMES_ADJ_WINDOWS,
    })
    specs["full_distance"] = {"actual": None, "cols": fd_variants, "filter": "target_score_complete"}
    return specs


def _apply_filter(df: pd.DataFrame, filter_col) -> pd.DataFrame:
    if filter_col is None:
        return df
    mask = df[filter_col].astype("boolean").fillna(False)
    return df.loc[mask.to_numpy(dtype="bool")]


def evaluate_numeric_markets(df: pd.DataFrame, tour: str) -> tuple[list[dict], list[dict]]:
    metric_rows: list[dict] = []
    count_rows: list[dict] = []
    specs = _numeric_market_specs(df.columns)

    for fold_name, train, test in iter_folds(df):
        for market, spec in specs.items():
            train_f = _apply_filter(train, spec["filter"])
            test_f = _apply_filter(test, spec["filter"])
            segs = _segments(test_f)

            # baseline trivial (item 10/11): media do alvo no fold de TREINO,
            # aplicada constante a todo o fold de teste -- referencia minima
            # que qualquer modelo "de verdade" precisa superar para o
            # esforco de modelagem se justificar.
            train_mean = pd.to_numeric(train_f[spec["actual"]], errors="coerce").mean()
            test_f = test_f.assign(_naive_train_mean=train_mean)

            cols_with_naive = list(spec["cols"]) + [("naive_train_mean", "none", "_naive_train_mean")]
            for variant, window, pred_col in cols_with_naive:
                if pred_col not in test_f.columns:
                    continue
                for (seg_type, seg_val), mask in segs.items():
                    sub = test_f.loc[mask]
                    m = numeric_metrics(sub[spec["actual"]], sub[pred_col])
                    metric_rows.append({
                        "tour": tour.upper(), "fold": fold_name, "market": market,
                        "variant": variant, "window": window,
                        "segment_type": seg_type, "segment_value": seg_val,
                        **m,
                    })
                if market in _count_market_keys():
                    cd = evaluate_count_market(train_f, test_f, spec["actual"], pred_col)
                    count_rows.append({
                        "tour": tour.upper(), "fold": fold_name, "market": market,
                        "variant": variant, "window": window, **cd,
                    })
    return metric_rows, count_rows


def evaluate_prob_markets(df: pd.DataFrame, tour: str) -> list[dict]:
    rows: list[dict] = []
    specs = _prob_market_specs()

    for fold_name, train, test in iter_folds(df):
        train_f = _apply_filter(train, specs["tiebreak"]["filter"])
        test_f = _apply_filter(test, specs["tiebreak"]["filter"])
        segs = _segments(test_f)

        for market_name, spec in specs.items():
            if market_name == "full_distance":
                best_of_test = test_f["best_of"].to_numpy(dtype="float64")
                actual_binary = pd.Series(
                    (pd.to_numeric(test_f["target_total_sets"], errors="coerce").to_numpy() == best_of_test).astype("float64"),
                    index=test_f.index,
                )
                best_of_train = train_f["best_of"].to_numpy(dtype="float64")
                train_actual_binary = pd.Series(
                    (pd.to_numeric(train_f["target_total_sets"], errors="coerce").to_numpy() == best_of_train).astype("float64"),
                    index=train_f.index,
                )
            else:
                actual_binary = pd.to_numeric(test_f[spec["actual"]], errors="coerce")
                train_actual_binary = pd.to_numeric(train_f[spec["actual"]], errors="coerce")

            # baseline trivial (item 10/11): taxa-base do fold de TREINO,
            # aplicada constante ao teste -- referencia minima de comparacao.
            train_base_rate = train_actual_binary.mean()
            test_f = test_f.assign(_naive_baserate=train_base_rate)

            cols_with_naive = list(spec["cols"]) + [("naive_baserate", "none", "_naive_baserate")]
            for variant, window, pred_col in cols_with_naive:
                if pred_col not in test_f.columns:
                    continue
                for (seg_type, seg_val), mask in segs.items():
                    sub_mask = mask
                    yt = actual_binary.loc[sub_mask]
                    yp = test_f.loc[sub_mask, pred_col]
                    b = brier_score(yt, yp)
                    ce = calibration_error(yt, yp) if b["n"] and b["n"] >= 20 else None
                    rows.append({
                        "tour": tour.upper(), "fold": fold_name, "market": market_name,
                        "variant": variant, "window": window,
                        "segment_type": seg_type, "segment_value": seg_val,
                        "n": b["n"], "brier": b["brier"], "log_loss": b["log_loss"],
                        "calibration_error": ce,
                    })

        # regressao logistica de tie-break (item 2): ajustada SO no treino
        preds, clf = fit_and_predict_tiebreak_logit(train_f, test_f, "target_has_tiebreak")
        test_f = test_f.assign(_logit_pred=preds)
        yt_all = pd.to_numeric(test_f["target_has_tiebreak"], errors="coerce")
        for (seg_type, seg_val), mask in segs.items():
            yt = yt_all.loc[mask]
            yp = test_f.loc[mask, "_logit_pred"]
            b = brier_score(yt, yp)
            ce = calibration_error(yt, yp) if b["n"] and b["n"] >= 20 else None
            rows.append({
                "tour": tour.upper(), "fold": fold_name, "market": "tiebreak",
                "variant": "logistic_regression", "window": "career",
                "segment_type": seg_type, "segment_value": seg_val,
                "n": b["n"], "brier": b["brier"], "log_loss": b["log_loss"],
                "calibration_error": ce,
            })
    return rows
