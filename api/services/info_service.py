"""Servico de metadados da API (GET /api/info).

So LEITURA de configuracao ja existente em src/ -- nenhum valor e
recalculado ou inventado aqui (docs/018_PWA_ARQUITETURA.md secao 4.4).
"""

from __future__ import annotations

from datetime import date

from src.forward import config as forward_cfg
from src.odds import config as odds_cfg
from src.odds import pricing_compare

from api.config import Settings
from api.schemas.common import InfoResponse


def _historical_data_cutoff() -> date | None:
    """Reaproveita src.odds.pricing_compare.staleness_warning (Fase 9),
    ja usado pelo forward test (src/forward/versioning.py). Tenta ATP e
    depois WTA; devolve None (nunca um valor inventado) se a base
    historica processada nao existir no ambiente atual."""
    for tour in ("ATP", "WTA"):
        try:
            stale = pricing_compare.staleness_warning(tour)
            return date.fromisoformat(stale["historical_data_cutoff"])
        except Exception:
            continue
    return None


def build_info(settings: Settings) -> InfoResponse:
    return InfoResponse(
        app=settings.app_name,
        api_version=settings.api_version,
        timezone=settings.default_timezone,
        default_bookmaker=odds_cfg.DEFAULT_BOOKMAKER,
        historical_data_cutoff=_historical_data_cutoff(),
        forward_version_id=forward_cfg.FORWARD_VERSION_ID,
    )
