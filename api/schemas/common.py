"""Schemas compartilhados (LOTE A). Um arquivo por dominio novo entra a
partir do LOTE C, conforme docs/018_PWA_ARQUITETURA.md secao 8.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app: str


class InfoResponse(BaseModel):
    app: str
    api_version: str
    timezone: str
    default_bookmaker: str
    # None quando a base historica (data/processed/*/matches.parquet) nao
    # estiver disponivel no ambiente -- nunca inventado (docs/018 secao 4.4).
    historical_data_cutoff: date | None = None
    forward_version_id: str
