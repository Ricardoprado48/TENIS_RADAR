from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from api.schemas.odds_evaluation import EvaluateResponse
from api.schemas.screenshots import (
    ConfirmRequest,
    ConfirmResponse,
    ExtractionResponse,
    ScreenshotUploadResponse,
    TabType,
)
from api.services import odds_evaluation_service, screenshot_service
from src.odds.screenshot_evaluation import (
    MatchContextUnavailableError,
    NoConfirmedExtractionError,
    UploadNotFoundError,
)
from src.screenshot_parser import extractor
from src.screenshot_parser.providers import ProviderResponseError, ProviderTimeoutError, ProviderUnavailableError
from src.screenshot_parser.storage import InvalidScreenshotError

router = APIRouter(tags=["screenshots"])


@router.post("/screenshots", response_model=ScreenshotUploadResponse, status_code=201)
async def post_screenshot(
    image: UploadFile = File(...),
    match_key: str = Form(...),
    tab_type: TabType = Form(...),
) -> ScreenshotUploadResponse:
    try:
        return await screenshot_service.upload_screenshot(
            image=image, match_key=match_key, tab_type=tab_type.value
        )
    except InvalidScreenshotError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/screenshots/{upload_id}/extract", response_model=ExtractionResponse)
def post_extract(upload_id: str) -> ExtractionResponse:
    try:
        return screenshot_service.extract_screenshot(upload_id)
    except extractor.ScreenshotNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Upload nao encontrado.") from exc
    except extractor.ScreenshotImageMissingError as exc:
        raise HTTPException(status_code=404, detail="Imagem original nao encontrada em disco.") from exc
    except ProviderTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/screenshots/{upload_id}/extraction", response_model=ExtractionResponse)
def get_extraction(upload_id: str) -> ExtractionResponse:
    try:
        return screenshot_service.get_extraction(upload_id)
    except extractor.ScreenshotNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Upload nao encontrado.") from exc
    except extractor.ExtractionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Nenhuma extracao encontrada para este upload.") from exc


@router.post("/screenshots/{upload_id}/confirm", response_model=ConfirmResponse)
def post_confirm(upload_id: str, body: ConfirmRequest) -> ConfirmResponse:
    try:
        return screenshot_service.confirm_screenshot(upload_id, body.markets)
    except extractor.ScreenshotNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Upload nao encontrado.") from exc
    except extractor.ScreenshotImageMissingError as exc:
        raise HTTPException(status_code=404, detail="Imagem original nao encontrada em disco.") from exc
    except extractor.ExtractionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/screenshots/{upload_id}/evaluate", response_model=EvaluateResponse)
def post_evaluate(upload_id: str) -> EvaluateResponse:
    try:
        return odds_evaluation_service.evaluate_confirmed_markets(upload_id)
    except UploadNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Upload nao encontrado.") from exc
    except NoConfirmedExtractionError as exc:
        raise HTTPException(status_code=404, detail="Nenhuma leitura confirmada para este upload.") from exc
    except MatchContextUnavailableError as exc:
        raise HTTPException(
            status_code=422,
            detail="Contexto da partida (tour) indisponivel na agenda -- avaliacao nao pode rodar.",
        ) from exc
