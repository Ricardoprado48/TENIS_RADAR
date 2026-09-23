"""Servico de calendario (GET /api/calendar, docs/018_PWA_ARQUITETURA.md
secao 5.2). So instancia o provider e adapta para os schemas Pydantic --
nenhuma logica de dominio mora aqui (fica em src/calendar/)."""

from __future__ import annotations

from datetime import date

from src.calendar.manual_provider import ManualFileCalendarProvider
from src.calendar.providers import CalendarProvider

from api.schemas.calendar import MatchSchedule


def _default_provider() -> CalendarProvider:
    return ManualFileCalendarProvider()


def list_matches(
    date_from: date,
    date_to: date,
    tour: str | None = None,
    tournament: str | None = None,
    provider: CalendarProvider | None = None,
) -> list[MatchSchedule]:
    provider = provider if provider is not None else _default_provider()
    matches = provider.list_matches(date_from, date_to, tour=tour, tournament=tournament)
    return [MatchSchedule(**vars(m)) for m in matches]
