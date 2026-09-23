from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Query

from api.schemas.calendar import MatchSchedule
from api.services import calendar_service

router = APIRouter(tags=["calendar"])


@router.get("/calendar", response_model=list[MatchSchedule])
def get_calendar(
    date_from: date = Query(..., description="Data inicial (America/Sao_Paulo), inclusiva"),
    date_to: date = Query(..., description="Data final (America/Sao_Paulo), inclusiva"),
    tour: Literal["ATP", "WTA"] | None = Query(None),
    tournament: str | None = Query(None),
) -> list[MatchSchedule]:
    return calendar_service.list_matches(date_from, date_to, tour=tour, tournament=tournament)
