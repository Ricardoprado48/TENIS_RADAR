"""Servico de screenshots: upload (LOTE E) + leitura/confirmacao (LOTE F).

Camada HTTP fina sobre `src.screenshot_parser` -- nenhuma logica de
validacao/armazenamento/extracao mora aqui, so a adaptacao entre
UploadFile/Pydantic e as funcoes de `src/` ja testadas isoladamente (mesmo
padrao de `api/services/radar_service.py` e `api/services/calendar_service.py`).
"""

from __future__ import annotations

from fastapi import UploadFile

from src.screenshot_parser import extractor, storage

from api.schemas.screenshots import (
    ConfirmMarketInput,
    ConfirmResponse,
    ExtractionResponse,
    NormalizedMarketSchema,
    ScreenshotUploadResponse,
)


async def upload_screenshot(*, image: UploadFile, match_key: str, tab_type: str) -> ScreenshotUploadResponse:
    content = await image.read()
    record = storage.save_screenshot(
        content=content,
        original_filename=image.filename or "",
        match_key=match_key,
        tab_type=tab_type,
    )
    return ScreenshotUploadResponse(
        upload_id=record.upload_id,
        match_key=record.match_key,
        tab_type=record.tab_type,
        bookmaker=record.bookmaker,
        created_at=record.created_at,
        mime_type=record.mime_type,
        file_size=record.file_size,
    )


def _market_to_schema(m) -> NormalizedMarketSchema:
    return NormalizedMarketSchema(
        market=m.market,
        player=m.player,
        bookmaker_display=m.bookmaker_display,
        side=m.side,
        model_line=m.model_line,
        decimal_odds=m.decimal_odds,
        confidence=m.confidence,
        warnings=list(m.warnings),
        needs_confirmation=m.needs_confirmation,
    )


def _extraction_to_schema(result) -> ExtractionResponse:
    return ExtractionResponse(
        extraction_id=result.extraction_id,
        upload_id=result.upload_id,
        match_key=result.match_key,
        tab_type=result.tab_type,
        status=result.status,
        provider=result.provider,
        provider_model=result.provider_model,
        created_at=result.created_at,
        markets=[_market_to_schema(m) for m in result.markets],
        extraction_warnings=list(result.extraction_warnings),
    )


def extract_screenshot(upload_id: str) -> ExtractionResponse:
    result = extractor.run_extraction(upload_id)
    return _extraction_to_schema(result)


def get_extraction(upload_id: str) -> ExtractionResponse:
    result = extractor.latest_extraction(upload_id)
    if result is None:
        raise extractor.ExtractionNotFoundError(upload_id)
    return _extraction_to_schema(result)


def confirm_screenshot(upload_id: str, markets: list[ConfirmMarketInput]) -> ConfirmResponse:
    edited = [m.model_dump() for m in markets]
    confirmed = extractor.confirm_extraction(upload_id, edited)
    return ConfirmResponse(
        extraction_id=confirmed.extraction_id,
        upload_id=confirmed.upload_id,
        match_key=confirmed.match_key,
        tab_type=confirmed.tab_type,
        confirmed_at=confirmed.confirmed_at,
        confirmed_by=confirmed.confirmed_by,
        corrected=confirmed.corrected,
        markets=[_market_to_schema(m) for m in confirmed.markets],
    )
