"""Interface do provedor de calendario (docs/018_PWA_ARQUITETURA.md secao
5.2). So o contrato -- nenhuma implementacao aqui. `api/services/calendar_service.py`
so instancia uma implementacao e adapta para os schemas Pydantic (secao
5.2); nenhuma logica de dominio mora em `api/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


@dataclass(frozen=True)
class Tournament:
    tour: str
    tournament: str
    surface: str
    country: str | None = None


@dataclass(frozen=True)
class MatchSchedule:
    match_key: str
    tour: str
    tournament: str
    round: str
    surface: str
    player_a: str
    player_b: str
    event_datetime_original: datetime
    event_timezone: str
    event_datetime_utc: datetime
    event_datetime_sao_paulo: datetime
    status: str
    collected_at: datetime
    source_url: str | None = None


class CalendarProvider(Protocol):
    def list_tournaments(self, date_from: date, date_to: date) -> list[Tournament]: ...

    def list_matches(
        self,
        date_from: date,
        date_to: date,
        tour: str | None = None,
        tournament: str | None = None,
    ) -> list[MatchSchedule]: ...

    def get_match(self, match_key: str) -> MatchSchedule | None: ...
