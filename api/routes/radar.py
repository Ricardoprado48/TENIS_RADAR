from __future__ import annotations

from fastapi import APIRouter

from api.schemas.radar import RadarLine
from api.services import radar_service

router = APIRouter(tags=["radar"])


@router.get("/radar/today", response_model=list[RadarLine])
def get_radar_today() -> list[RadarLine]:
    return radar_service.get_radar_lines()
