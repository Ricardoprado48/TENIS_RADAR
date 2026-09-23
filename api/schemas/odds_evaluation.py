"""Contratos do LOTE G (docs/018_PWA_ARQUITETURA.md secao 14): avaliacao
dos mercados CONFIRMADOS do LOTE F contra o pipeline ja existente das
Fases 9/10. Espelha `src.odds.screenshot_evaluation.evaluate_confirmed` --
nenhum campo e calculado aqui, so serializado.

LOTE H (secao 22) acrescentou `ForwardKey`/`prediction_id`/
`already_registered_forward_test` -- so identidade/estado de registro
(`api/services/odds_evaluation_service.py` computa via
`src.forward.ids`/`src.forward.build.is_registered`), nenhuma probabilidade/
odd/classificacao nova."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

__all__ = [
    "EvaluationLabel",
    "TechnicalDetails",
    "ForwardKey",
    "EvaluatedMarketResult",
    "EvaluateResponse",
]

EvaluationLabel = Literal[
    "PASSOU_DO_LIMITE", "OBSERVAR", "NAO_PASSOU", "SEM_AVALIACAO_DISPONIVEL",
]


class TechnicalDetails(BaseModel):
    """Secao colapsavel "Detalhes tecnicos" do pedido -- nunca exibida por
    padrao na tela principal."""

    implied_probability: float | None = None
    model_edge: float | None = None
    sample_quality: str | None = None
    matched: bool | None = None
    match_reason: str | None = None
    data_staleness_days: int | float | None = None
    restricted_motivo: str | None = None


class ForwardKey(BaseModel):
    """Chave natural (Fase 9/10) desta linha ja avaliada -- usada so pelo
    botao "Registrar no Forward Test" (LOTE H) para identificar a
    oportunidade, nunca para recalcular nada aqui."""

    bookmaker: str
    tour: str
    match_id: str
    market: str
    player: str | None = None
    side: str
    line: float
    decimal_odds: float
    collected_at: str


class EvaluatedMarketResult(BaseModel):
    market: str
    player: str | None = None
    bookmaker_display: str
    model_line: float | None = None
    side: str | None = None
    bookmaker_odds: float

    model_probability: float | None = None
    fair_odds: float | None = None
    minimum_odds: float | None = None

    decision_state: str | None = None
    evaluation_label: EvaluationLabel
    evaluation_message: str | None = None

    staleness_status: str | None = None
    restricted: bool | None = None

    technical: TechnicalDetails | None = None
    forward_key: ForwardKey | None = None
    prediction_id: str | None = None
    already_registered_forward_test: bool = False
    error: str | None = None


class EvaluateResponse(BaseModel):
    upload_id: str
    extraction_id: str
    match_key: str
    confirmed_at: datetime

    historical_data_cutoff: str | None = None
    data_staleness_days: int | None = None
    staleness_warning: str | None = None

    results: list[EvaluatedMarketResult]
