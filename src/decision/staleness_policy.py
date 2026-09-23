"""Politica de staleness (item 6): classifica `data_staleness_days` (ja
calculado pela Fase 9, `src.odds.pricing_compare.staleness_warning`) em 3
faixas objetivas, e decide se `CANDIDATO_FORTE` fica bloqueado.

Nunca esconde a defasagem -- o texto de aviso ja produzido pela Fase 9
continua sendo propagado sem alteracao (ver `inputs.py`)."""

from __future__ import annotations

from . import config as cfg


def classify_staleness(data_staleness_days) -> str:
    if data_staleness_days is None or data_staleness_days != data_staleness_days:  # NaN
        # item 6: staleness precisa estar EXPLICITAMENTE registrada -- dado
        # ausente nunca e tratado como "atual", cai no pior caso.
        return cfg.STALENESS_MUITO_DEFASADO

    days = int(data_staleness_days)
    if days <= cfg.STALENESS_ATUAL_MAX_DAYS:
        return cfg.STALENESS_ATUAL
    if days <= cfg.STALENESS_MODERADO_MAX_DAYS:
        return cfg.STALENESS_MODERADO
    return cfg.STALENESS_MUITO_DEFASADO


def blocks_candidato_forte(staleness_bucket: str) -> bool:
    """item 6: 'nao permitir classificacao CANDIDATO_FORTE quando a
    defasagem ultrapassar o limite definido'."""

    return staleness_bucket == cfg.STALENESS_MUITO_DEFASADO
