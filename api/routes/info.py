from __future__ import annotations

from fastapi import APIRouter, Depends

from api.config import Settings
from api.deps import get_settings
from api.schemas.common import InfoResponse
from api.services.info_service import build_info

router = APIRouter(tags=["info"])


@router.get("/info", response_model=InfoResponse)
def info(settings: Settings = Depends(get_settings)) -> InfoResponse:
    return build_info(settings)
