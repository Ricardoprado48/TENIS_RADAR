from __future__ import annotations

from fastapi import APIRouter, Depends

from api.config import Settings
from api.deps import get_settings
from api.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(status="ok", app=settings.app_name)
