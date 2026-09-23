"""Recalibra a probabilidade Negative Binomial de partidas futuras (item 1
da instrucao: "usar a probabilidade operacional definida na Fase 6.1").

O modelo de calibracao (Platt/Isotonic) ajustado pela Fase 6.1 NAO e
persistido em disco -- so a probabilidade calibrada resultante, para as
linhas historicas que ja existiam naquela fase (ver
src/recalibration/build.py `_apply_calibration_for_tour_market`, que ajusta
o calibrador em memoria e descarta). Para aplicar a MESMA regra a uma
probabilidade nova (de uma partida futura), este modulo reajusta o
calibrador -- reproduzindo exatamente os mesmos dados de treino e o mesmo
metodo que a Fase 6.1 ja usou para o fold vigente (fold_2026: treino =
fold_2024 + fold_2025, ver src/recalibration/config.py
CALIBRATION_TRAIN_FOLDS), nunca re-decidindo qual metodo usar -- o metodo
(`raw`/`platt`/`isotonic`) vem de
`data/outputs/phase6_1/selecao_metodo_por_mercado.csv`, ja decidido e
nunca alterado aqui.

Isso reproduz byte a byte o calibrador que a Fase 6.1 aplicou as linhas
reais de fold_2026 -- verificado em tests/test_radar.py
(consistencia com a Fase 7)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.recalibration import methods as meth

from . import config as cfg


@dataclass(frozen=True)
class FittedCalibrator:
    tour: str
    market: str
    method_selected_config: str
    calibrator: object
    fit_status: str
    train_n: int


def load_method_selected() -> pd.DataFrame:
    return pd.read_csv(cfg.PHASE6_1_METHOD_PATH)


def _training_data(phase6_df: pd.DataFrame, tour: str, market: str) -> tuple[np.ndarray, np.ndarray, int]:
    train_folds = cfg.CALIBRATION_TRAIN_FOLDS[cfg.CURRENT_FOLD]
    sub = phase6_df[
        (phase6_df["tour"] == tour) & (phase6_df["market"] == market) & (phase6_df["fold"].isin(train_folds))
    ]
    sub = sub.dropna(subset=["p_over_negbin", "actual_over"])
    p_raw = sub["p_over_negbin"].to_numpy(dtype="float64")
    y = sub["actual_over"].to_numpy(dtype="float64")
    return p_raw, y, len(sub)


def build_calibrators(phase6_df: pd.DataFrame) -> dict[tuple[str, str], FittedCalibrator]:
    method_df = load_method_selected()
    out: dict[tuple[str, str], FittedCalibrator] = {}
    for tour in cfg.TOURS:
        for market in cfg.MARKETS:
            row = method_df[(method_df["tour"] == tour) & (method_df["market"] == market)]
            method = str(row.iloc[0]["method_selected"]) if not row.empty else "raw"
            p_raw, y, n_train = _training_data(phase6_df, tour, market)
            calibrator, status = meth.fit_calibrator(method, p_raw, y)
            out[(tour, market)] = FittedCalibrator(
                tour=tour, market=market, method_selected_config=method,
                calibrator=calibrator, fit_status=status, train_n=n_train,
            )
    return out


def apply_calibration(predictions: pd.DataFrame, calibrators: dict[tuple[str, str], FittedCalibrator]) -> pd.DataFrame:
    if predictions.empty:
        return predictions

    df = predictions.copy()
    df["raw_probability"] = df["p_over_negbin"]
    calibrated = np.full(len(df), np.nan, dtype="float64")
    method_selected = np.full(len(df), "unavailable", dtype=object)
    calibrator_train_n = np.zeros(len(df), dtype="int64")

    for (tour, market), fc in calibrators.items():
        mask = (df["tour"] == tour).to_numpy() & (df["market"] == market).to_numpy()
        if not mask.any():
            continue
        p_raw = df.loc[mask, "raw_probability"].to_numpy(dtype="float64")
        calibrated[mask] = fc.calibrator.predict(p_raw)
        method_selected[mask] = fc.fit_status
        calibrator_train_n[mask] = fc.train_n

    df["calibrated_probability"] = calibrated
    df["method_selected"] = method_selected
    df["calibrator_train_n"] = calibrator_train_n
    return df
