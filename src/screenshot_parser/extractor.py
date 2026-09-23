"""Orquestracao da leitura de print (docs/018 secao 7.1, arquivo sugerido
pelo pedido do LOTE F). Junta storage (LOTE E) + providers + mapping +
validator + extraction_storage -- a unica camada que `api/services/
screenshot_service.py` chama, sem reimplementar nenhuma regra aqui.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from . import config as cfg
from . import extraction_storage, providers, storage, validator
from .models import ConfirmedExtraction, ExtractionResult, MatchContext, RawReading


class ScreenshotNotFoundError(LookupError):
    """`upload_id` nao corresponde a nenhum print gravado (LOTE E)."""


class ScreenshotImageMissingError(LookupError):
    """O sidecar existe, mas o arquivo de imagem nao esta mais em disco --
    nunca deveria acontecer (imagem original e imutavel), mas nunca
    inventa um resultado se isso ocorrer."""


class ExtractionNotFoundError(LookupError):
    """Nenhuma extracao foi rodada ainda para este `upload_id`."""


class ExtractionValidationError(ValueError):
    """Pelo menos uma leitura enviada para confirmacao tem um erro
    estrutural grave (secao "CONFIRMACAO": so isso bloqueia)."""

    def __init__(self, blocking_markets):
        self.blocking_markets = list(blocking_markets)
        codes = sorted({w for m in blocking_markets for w in m.warnings if w in validator.STRUCTURAL_BLOCKING_WARNINGS})
        super().__init__(f"Leitura tem erro estrutural grave e nao pode ser confirmada: {', '.join(codes)}.")


def _build_match_context(match_key: str) -> MatchContext | None:
    """Secao "CONTEXTO DA PARTIDA" do pedido -- usa o mesmo
    ManualFileCalendarProvider do LOTE C, nunca duplica a leitura/validacao
    de agenda_*.csv. Se a agenda nao tiver a partida (ou nao existir),
    devolve None -- validator.py trata isso como "sem contexto para
    conferir o jogador", nunca inventa um valor."""
    try:
        from src.calendar.manual_provider import ManualFileCalendarProvider

        match = ManualFileCalendarProvider().get_match(match_key)
    except Exception:
        return None
    if match is None:
        return None
    return MatchContext(
        match_key=match_key,
        tour=match.tour,
        tournament=match.tournament,
        player_a=match.player_a,
        player_b=match.player_b,
    )


def get_match_context(match_key: str) -> MatchContext | None:
    """Wrapper publico -- LOTE G (avaliacao de odds) precisa do mesmo
    contexto de partida para casar a leitura confirmada contra o radar,
    sem duplicar a leitura/validacao de agenda_*.csv feita aqui. Chama
    `_build_match_context` por nome (nao por referencia direta) para
    continuar respeitando `mock.patch("...extractor._build_match_context")`
    ja usado pela suite do LOTE F (`tests/test_screenshot_extraction_api.py`)."""
    return _build_match_context(match_key)


def _load_screenshot(upload_id: str):
    record = storage.find_screenshot(upload_id)
    if record is None:
        raise ScreenshotNotFoundError(upload_id)
    try:
        image_path = storage.resolve_image_path(record)
    except FileNotFoundError as exc:
        raise ScreenshotImageMissingError(upload_id) from exc
    return record, image_path


def run_extraction(upload_id: str, *, provider: providers.ScreenshotVisionProvider | None = None) -> ExtractionResult:
    record, image_path = _load_screenshot(upload_id)
    context = _build_match_context(record.match_key)
    provider = provider or providers.get_provider()

    extraction_context = providers.ExtractionContext(match_context=context, tab_type=record.tab_type)
    provider_result = provider.extract(image_path, extraction_context)

    markets = validator.validate_and_normalize(provider_result.readings, context)
    status = validator.determine_status(markets)
    extraction_warnings = () if markets else (cfg.EXTRACTION_WARNING_NO_MARKETS_FOUND,)

    result = ExtractionResult(
        extraction_id=str(uuid.uuid4()),
        upload_id=upload_id,
        match_key=record.match_key,
        tab_type=record.tab_type,
        status=status,
        provider=provider.name,
        provider_model=provider_result.model,
        created_at=datetime.now(timezone.utc),
        markets=tuple(markets),
        extraction_warnings=extraction_warnings,
        raw_provider_response=provider_result.raw_response,
    )
    extraction_storage.save_raw_extraction(result)
    return result


def latest_extraction(upload_id: str) -> ExtractionResult | None:
    if storage.find_screenshot(upload_id) is None:
        raise ScreenshotNotFoundError(upload_id)
    return extraction_storage.latest_raw_extraction(upload_id)


def _markets_equal(a: tuple, b: tuple) -> bool:
    def key(m):
        return (m.market, m.player, m.bookmaker_display, m.side, m.model_line, m.decimal_odds)

    return sorted(map(key, a)) == sorted(map(key, b))


def confirm_extraction(upload_id: str, edited_markets: list[dict]) -> ConfirmedExtraction:
    record, _ = _load_screenshot(upload_id)
    context = _build_match_context(record.match_key)

    raw_readings = [
        RawReading(
            market=m["market"],
            player=m.get("player"),
            bookmaker_display=m["bookmaker_display"],
            decimal_odds=m["decimal_odds"],
            source_confidence=None,
        )
        for m in edited_markets
    ]
    normalized = validator.validate_and_normalize(raw_readings, context)

    blocking = [m for m in normalized if validator.is_structural_error(m)]
    if blocking:
        raise ExtractionValidationError(blocking)

    previous = extraction_storage.latest_raw_extraction(upload_id)
    corrected = previous is None or not _markets_equal(previous.markets, tuple(normalized))

    confirmed = ConfirmedExtraction(
        extraction_id=str(uuid.uuid4()),
        upload_id=upload_id,
        match_key=record.match_key,
        tab_type=record.tab_type,
        confirmed_at=datetime.now(timezone.utc),
        confirmed_by=cfg.CONFIRMED_BY_DEFAULT,
        corrected=corrected,
        markets=tuple(normalized),
    )
    extraction_storage.save_confirmed(confirmed)
    return confirmed
