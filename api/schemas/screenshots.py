"""Contratos de upload (LOTE E) e de leitura/confirmacao de print (LOTE F,
docs/018_PWA_ARQUITETURA.md secao 8 e instrucoes de cada lote). `TabType`
e reaproveitado de `src.screenshot_parser.config` -- nunca redefinido aqui
(mesma regra ja seguida para `Market`/`DecisionState` no LOTE D)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.screenshot_parser.config import TabType

__all__ = [
    "TabType",
    "ScreenshotUploadResponse",
    "ScreenshotMetadata",
    "NormalizedMarketSchema",
    "ExtractionResponse",
    "ConfirmMarketInput",
    "ConfirmRequest",
    "ConfirmResponse",
]

ExtractionMarket = Literal["aces_player", "total_aces_match", "total_games"]
ExtractionSide = Literal["Over", "Under"]
ExtractionStatus = Literal["AUTO_VALIDATED", "NEEDS_CONFIRMATION"]


class ScreenshotUploadResponse(BaseModel):
    """Devolvida ao frontend apos o upload. Nunca inclui `stored_path`
    completo nem `sha256` -- so o que a tela ENVIAR PRINT precisa mostrar
    ("Print salvo com sucesso" + upload_id)."""

    upload_id: str
    match_key: str
    tab_type: TabType
    bookmaker: str
    created_at: datetime
    mime_type: str
    file_size: int


class ScreenshotMetadata(ScreenshotUploadResponse):
    """Registro completo de auditoria (o mesmo JSON sidecar gravado em
    data/raw/bookmaker_screenshots/) -- inclui campos internos que o
    upload de resposta nao expoe."""

    original_filename: str
    stored_path: str
    sha256: str


class NormalizedMarketSchema(BaseModel):
    """Espelha `src.screenshot_parser.models.NormalizedMarket`. `side`/
    `model_line` sao `None` quando `bookmaker_display` nao pode ser
    interpretado (warning `FORMATO_ILEGIVEL`) -- nunca um valor inventado."""

    market: ExtractionMarket
    player: str | None = None
    bookmaker_display: str
    side: ExtractionSide | None = None
    model_line: float | None = None
    decimal_odds: float
    confidence: float | None = None
    warnings: list[str] = Field(default_factory=list)
    needs_confirmation: bool = False


class ExtractionResponse(BaseModel):
    """POST /api/screenshots/{upload_id}/extract e GET .../extraction."""

    extraction_id: str
    upload_id: str
    match_key: str
    tab_type: TabType
    status: ExtractionStatus
    provider: str
    provider_model: str | None = None
    created_at: datetime
    markets: list[NormalizedMarketSchema]
    extraction_warnings: list[str] = Field(default_factory=list)


class ConfirmMarketInput(BaseModel):
    """O que a tela LEITURA DO PRINT envia ao confirmar -- o usuario edita
    `player`/`bookmaker_display`/`decimal_odds`; `model_line`/`side` sao
    sempre recalculados no backend a partir de `bookmaker_display` (nunca
    editados diretamente, pedido explicito)."""

    market: ExtractionMarket
    player: str | None = None
    bookmaker_display: str
    decimal_odds: float


class ConfirmRequest(BaseModel):
    markets: list[ConfirmMarketInput]


class ConfirmResponse(BaseModel):
    extraction_id: str
    upload_id: str
    match_key: str
    tab_type: TabType
    confirmed_at: datetime
    confirmed_by: str
    corrected: bool
    markets: list[NormalizedMarketSchema]
