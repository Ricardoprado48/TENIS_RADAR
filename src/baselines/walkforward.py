"""Particionamento walk-forward (item 4) e segmentacoes (item 6/9).

Regra: treino = tudo antes de `train_end` (sempre a partir do inicio dos
dados -- janela expansiva, conforme exemplo do enunciado). Teste = o ano
seguinte. NUNCA random split. Qualquer parametro "ajustado" (dispersao
Negative Binomial, coeficientes de regressao logistica, limiares de
probabilidade) so pode usar linhas do fold de TREINO -- helpers abaixo
recebem sempre train_df/test_df separados para deixar isso explicito no
codigo de quem chama, e nao apenas na documentacao.
"""

from __future__ import annotations

import pandas as pd

from .config import FOLDS, RANKING_BUCKETS, SAMPLE_SIZE_BUCKETS


def split_fold(df: pd.DataFrame, fold: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    train_end = pd.Timestamp(fold["train_end"])
    test_start = pd.Timestamp(fold["test_start"])
    test_end = pd.Timestamp(fold["test_end"])
    train = df.loc[df["tournament_date"] <= train_end]
    test = df.loc[(df["tournament_date"] >= test_start) & (df["tournament_date"] <= test_end)]
    return train, test


def iter_folds(df: pd.DataFrame):
    for fold in FOLDS:
        train, test = split_fold(df, fold)
        if len(test) == 0:
            continue
        yield fold["name"], train, test


def sample_size_bucket(prior_matches: pd.Series) -> pd.Series:
    n = pd.to_numeric(prior_matches, errors="coerce")
    out = pd.Series(pd.array([None] * len(n), dtype="string"), index=n.index)
    for lo, hi, label in SAMPLE_SIZE_BUCKETS:
        if hi is None:
            mask = n >= lo
        else:
            mask = (n >= lo) & (n <= hi)
        out.loc[mask] = label
    return out


def ranking_bucket(rank: pd.Series) -> pd.Series:
    r = pd.to_numeric(rank, errors="coerce")
    out = pd.Series(pd.array([None] * len(r), dtype="string"), index=r.index)
    for lo, hi, label in RANKING_BUCKETS:
        if hi is None:
            mask = r >= lo
        else:
            mask = (r >= lo) & (r <= hi)
        out.loc[mask] = label
    return out
