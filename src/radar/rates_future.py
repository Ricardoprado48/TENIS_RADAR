"""Aplica os baselines de taxa da Fase 4 (lambda) as linhas sinteticas de
partidas futuras -- item 3/4 da instrucao. Nenhuma formula nova: reusa
`src.baselines.rate_models` linha a linha (mesmas colunas
`player_serve_*_{window}` / `opponent_return_*_{window}` ja calculadas pela
Fase 3 para as linhas sinteticas)."""

from __future__ import annotations

import pandas as pd

from src.baselines.rate_models import (
    add_ace_predictions,
    add_double_fault_predictions,
    add_total_aces_predictions,
)
from src.baselines.walkforward import sample_size_bucket


def add_all_predictions(future_rows: pd.DataFrame) -> pd.DataFrame:
    if future_rows.empty:
        return future_rows
    df = add_ace_predictions(future_rows)
    df = add_double_fault_predictions(df)
    df = add_total_aces_predictions(df)
    df["sample_bucket_career"] = sample_size_bucket(df["prior_matches_career"])
    return df
