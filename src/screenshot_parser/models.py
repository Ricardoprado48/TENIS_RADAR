"""Estruturas de dados do LOTE F (docs/018_PWA_ARQUITETURA.md secao 7.2).

So dataclasses simples (mesmo padrao de `src/calendar/providers.py` e
`src/screenshot_parser/storage.py::ScreenshotRecord`) -- nenhuma
dependencia de framework web aqui, para o modulo continuar testavel sem
subir a API.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class MatchContext:
    """Contexto da partida (secao "CONTEXTO DA PARTIDA" do pedido) -- usado
    para validar o jogador citado no print, nunca para inventar um valor
    que nao apareca na imagem."""

    match_key: str
    tour: str | None
    tournament: str | None
    player_a: str | None
    player_b: str | None


@dataclass(frozen=True)
class RawReading:
    """Uma leitura bruta devolvida por um `ScreenshotVisionProvider`, antes
    de mapping.py/validator.py normalizarem `bookmaker_display` em
    `model_line`/`side`."""

    market: str  # "aces_player" | "total_aces_match" | "total_games"
    player: str | None  # None em mercados de partida
    bookmaker_display: str  # texto bruto: "6+", "Mais de 22.5", etc.
    decimal_odds: float
    source_confidence: float | None = None


@dataclass(frozen=True)
class NormalizedMarket:
    """Mercado normalizado (secao "FORMATO NORMALIZADO" do pedido), com o
    resultado das checagens de validator.py ja aplicado."""

    market: str
    player: str | None
    bookmaker_display: str
    side: str | None  # "Over" | "Under" -- None quando o display nao foi legivel
    model_line: float | None  # None quando o display nao foi legivel
    decimal_odds: float
    confidence: float | None
    warnings: tuple[str, ...] = ()
    needs_confirmation: bool = False

    def to_json_dict(self) -> dict:
        data = asdict(self)
        data["warnings"] = list(self.warnings)
        return data


@dataclass(frozen=True)
class ExtractionResult:
    """Resultado intermediario de uma extracao (secao "CAMADA DE EXTRACAO"
    do pedido) -- gravado tal como esta em `data/raw/bookmaker_extracted/`,
    nunca reescrito."""

    extraction_id: str
    upload_id: str
    match_key: str
    tab_type: str
    status: str  # AUTO_VALIDATED | NEEDS_CONFIRMATION
    provider: str
    provider_model: str | None
    created_at: datetime
    markets: tuple[NormalizedMarket, ...] = ()
    extraction_warnings: tuple[str, ...] = ()
    raw_provider_response: str | None = None

    def to_json_dict(self) -> dict:
        return {
            "extraction_id": self.extraction_id,
            "upload_id": self.upload_id,
            "match_key": self.match_key,
            "tab_type": self.tab_type,
            "status": self.status,
            "provider": self.provider,
            "provider_model": self.provider_model,
            "created_at": self.created_at.isoformat(),
            "markets": [m.to_json_dict() for m in self.markets],
            "extraction_warnings": list(self.extraction_warnings),
            "raw_provider_response": self.raw_provider_response,
        }


@dataclass(frozen=True)
class ConfirmedExtraction:
    """Leitura confirmada pelo usuario (secao "CONFIRMACAO" do pedido) --
    gravada em `data/processed/bookmaker_confirmed/`, artefato separado da
    extracao bruta."""

    extraction_id: str
    upload_id: str
    match_key: str
    tab_type: str
    confirmed_at: datetime
    confirmed_by: str
    corrected: bool
    markets: tuple[NormalizedMarket, ...] = field(default_factory=tuple)

    def to_json_dict(self) -> dict:
        return {
            "extraction_id": self.extraction_id,
            "upload_id": self.upload_id,
            "match_key": self.match_key,
            "tab_type": self.tab_type,
            "confirmed_at": self.confirmed_at.isoformat(),
            "confirmed_by": self.confirmed_by,
            "corrected": self.corrected,
            "markets": [m.to_json_dict() for m in self.markets],
        }
