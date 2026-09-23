"""Tie-break: regressao logistica (item 2 pede explicitamente "regressao
logistica ou baseline baseado em Hold% combinado") -- aqui os DOIS sao
avaliados lado a lado, o baseline Hold% combinado ja vem de games_model.py
(`pred_p_tiebreak_{variant}_{w}`, via o modelo analitico de sets).

A regressao logistica e ajustada (fit) SOMENTE no fold de treino, com
features simples e ja point-in-time (Hold% dos dois lados na janela
`career`, mais dummies de superficie) -- nunca no fold de teste, nunca com
dado da propria partida a ser prevista."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

_FEATURE_COLS = [
    "player_serve_hold_pct_career", "opponent_serve_hold_pct_career",
    "player_return_break_pct_career", "opponent_return_break_pct_career",
]
_SURFACES = ["Hard", "Clay", "Grass"]


def _design_matrix(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    base = df[_FEATURE_COLS].apply(pd.to_numeric, errors="coerce")
    surf_dummies = pd.get_dummies(df["surface"].where(df["surface"].isin(_SURFACES)), dtype="float64")
    for s in _SURFACES:
        if s not in surf_dummies.columns:
            surf_dummies[s] = 0.0
    surf_dummies = surf_dummies[_SURFACES]
    X = pd.concat([base, surf_dummies], axis=1)
    mask = X[_FEATURE_COLS].notna().all(axis=1).to_numpy()
    return X.to_numpy(dtype="float64"), mask


def fit_and_predict_tiebreak_logit(train_df: pd.DataFrame, test_df: pd.DataFrame, target_col: str):
    """Ajusta em train_df, preve probabilidade para test_df. Retorna um
    np.ndarray (mesmo tamanho de test_df, NaN onde nao ha feature
    suficiente) e o classificador ajustado (para inspecao/relatorio)."""

    X_train, mask_train = _design_matrix(train_df)
    y_train = pd.to_numeric(train_df[target_col], errors="coerce").to_numpy(dtype="float64")
    mask_train = mask_train & np.isfinite(y_train)
    X_train, y_train = X_train[mask_train], y_train[mask_train]

    n_test = len(test_df)
    preds = np.full(n_test, np.nan)
    if len(np.unique(y_train)) < 2 or X_train.shape[0] < 50:
        return preds, None  # treino insuficiente -- nao inventa previsao

    clf = LogisticRegression(max_iter=1000)
    clf.fit(X_train, y_train)

    X_test, mask_test = _design_matrix(test_df)
    if mask_test.any():
        preds[mask_test] = clf.predict_proba(X_test[mask_test])[:, 1]
    return preds, clf
