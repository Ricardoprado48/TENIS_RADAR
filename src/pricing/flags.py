"""Flags de qualidade/restricao aplicadas a cada linha precificada (itens 5
e 6). Nenhuma flag remove ou oculta a linha -- apenas marca; a probabilidade
e a odd continuam visiveis (exceto cold start, que explicitamente nao
recebe preco -- item 6)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as cfg


def cold_start_flag(sample_bucket_career: pd.Series) -> pd.Series:
    return sample_bucket_career == "cold_start"


def insufficient_history_flag(sample_bucket_career: pd.Series) -> pd.Series:
    """Amostra pequena mas nao nula (item 6: "preservar flag e nao
    ocultar" -- diferente de cold start, ainda recebe preco)."""

    return sample_bucket_career == "small_1_9"


def calibrator_insufficient_sample_flag(calibrator_train_n: pd.Series, method_selected: pd.Series) -> pd.Series:
    """Amostra do CALIBRADOR (nao do jogador) abaixo do minimo exigido na
    Fase 6.1, para um metodo que nao seja raw. Na pratica nunca ocorre com
    os dados atuais (treino minimo observado >> MIN_CALIBRATOR_TRAIN_N), mas
    a flag existe para nao esconder o caso se ele aparecer em dados
    futuros."""

    uses_calibrator = ~method_selected.isin(["raw", "raw_sem_periodo_anterior"])
    return uses_calibrator & (calibrator_train_n < cfg.MIN_CALIBRATOR_TRAIN_N)


def extreme_probability_flag(probability: pd.Series) -> pd.Series:
    """item 6: probabilidade >= 90% exige cautela, nao e tratada como
    previsao automaticamente superior."""

    return probability >= cfg.EXTREME_PROBABILITY_THRESHOLD


def restricted_flag(tour: pd.Series, market: pd.Series, surface: pd.Series) -> tuple[pd.Series, pd.Series]:
    """item 6: ATP aces_player em Grass -- marcado, nunca removido. Retorna
    (flag booleana, motivo textual ou None)."""

    restricted = pd.Series(False, index=tour.index)
    motivo = pd.Series(pd.NA, index=tour.index, dtype="object")
    for seg in cfg.RESTRICTED_SEGMENTS:
        mask = (tour == seg["tour"]) & (market == seg["market"]) & (surface == seg["surface"])
        restricted = restricted | mask
        motivo = motivo.where(~mask, seg["motivo"])
    return restricted, motivo
