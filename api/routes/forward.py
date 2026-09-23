from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from api.schemas.forward import (
    ForwardSummaryResponse,
    PredictionDetailResponse,
    PredictionListResponse,
    RegisterForwardRequest,
    RegisterForwardResponse,
)
from api.services import forward_service

router = APIRouter(tags=["forward"])


@router.get("/forward/summary", response_model=ForwardSummaryResponse)
def get_summary() -> ForwardSummaryResponse:
    return forward_service.get_summary()


@router.get("/forward/predictions", response_model=PredictionListResponse)
def get_predictions(
    tour: Literal["ATP", "WTA"] | None = Query(None),
    settlement_group: Literal["pendentes", "resolvidas"] | None = Query(None),
    classification_group: Literal["candidato", "observar", "descartado"] | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> PredictionListResponse:
    return forward_service.list_predictions(
        tour=tour, settlement_group=settlement_group, classification_group=classification_group,
        limit=limit, offset=offset,
    )


@router.get("/forward/predictions/{prediction_id}", response_model=PredictionDetailResponse)
def get_prediction(prediction_id: str) -> PredictionDetailResponse:
    try:
        return forward_service.get_prediction_detail(prediction_id)
    except forward_service.PredictionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Previsao nao encontrada.") from exc


@router.post("/forward/register", response_model=RegisterForwardResponse)
def post_register(payload: RegisterForwardRequest) -> RegisterForwardResponse:
    return forward_service.register_prediction(payload)
