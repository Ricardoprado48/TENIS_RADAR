"""Contratos do LOTE C (docs/018_PWA_ARQUITETURA.md secao 8)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Tournament(BaseModel):
    tour: Literal["ATP", "WTA"]
    tournament: str
    surface: Literal["Hard", "Clay", "Grass"]
    # Nenhuma coluna de pais existe em agenda_*.csv nesta fase -- exposto
    # explicitamente como None em vez de inventado (docs/018 secao 4.4).
    country: str | None = None


class MatchSchedule(BaseModel):
    match_key: str
    tour: Literal["ATP", "WTA"]
    tournament: str
    round: str
    surface: Literal["Hard", "Clay", "Grass"]
    player_a: str
    player_b: str
    event_datetime_original: datetime
    event_timezone: str
    event_datetime_utc: datetime
    event_datetime_sao_paulo: datetime
    status: Literal["futuro", "proximo", "iniciado", "encerrado"]
    source_url: str | None = None
    collected_at: datetime
