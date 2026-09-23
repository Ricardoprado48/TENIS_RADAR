"""Contratos do LOTE H (docs/018_PWA_ARQUITETURA.md secao 22): exposicao do
Forward Test (Fase 11) na PWA. Espelha `api/services/forward_service.py` --
nenhum campo aqui e calculado a partir de probabilidade/odd bruta; tudo vem
de `data/outputs/phase11/*.parquet`/`phase11_summary.json` (Fase 11) ou de
uma contagem/selecao simples sobre esses dados ja calculados."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "ForwardSummaryCounts",
    "ForwardResultCounts",
    "PaperTestSummary",
    "CalibrationBucket",
    "MarketTechnicalBreakdown",
    "ForwardTechnicalSummary",
    "ForwardSummaryResponse",
    "PredictionListItem",
    "PredictionListResponse",
    "OddsHistory",
    "ClvInfo",
    "PredictionTechnicalDetails",
    "PredictionDetailResponse",
    "RegisterForwardRequest",
    "RegisterForwardResponse",
]


class ForwardSummaryCounts(BaseModel):
    n_predictions_registered: int
    n_pending_settlement: int
    n_resolved: int
    n_candidates: int
    n_observar: int
    n_descartados: int


class ForwardResultCounts(BaseModel):
    wins: int
    losses: int
    void: int
    pending: int


class PaperTestSummary(BaseModel):
    """Espelha `src.forward.paper_test.summarize_paper_test` -- lido de
    `data/outputs/phase11/paper_test.parquet` (Fase 11), nunca recalculado
    aqui (item "PAPER TEST" do pedido: rotulo `PAPER_TEST_ONLY`,
    nunca linguagem de lucro garantido)."""

    label: str = "PAPER_TEST_ONLY"
    n_entries_simulated: int = 0
    n_wins: int | None = None
    n_losses: int | None = None
    n_voids: int | None = None
    n_pending_settlement: int | None = None
    total_staked_units: float | None = None
    total_pnl_units: float | None = None
    roi: float | None = None
    max_drawdown_units: float | None = None
    max_consecutive_losses: int | None = None
    outcome_distribution: dict[str, int] | None = None


class CalibrationBucket(BaseModel):
    bucket: str
    n: int
    mean_predicted: float | None = None
    observed_rate: float | None = None


class MarketTechnicalBreakdown(BaseModel):
    market: str
    n: int
    brier_score: float | None = None
    clv_avg_pct: float | None = None
    paper_roi: float | None = None


class ForwardTechnicalSummary(BaseModel):
    """"Detalhes tecnicos" do resumo -- Brier/Log Loss/calibracao, geral e
    por mercado. Calculado chamando `src.forward.metrics`/`clv`/`paper_test`
    diretamente (mesmas funcoes que `src.forward.build.cumulative_dashboard`
    ja usa para o relatorio texto), nunca reimplementado."""

    brier_score_overall: float | None = None
    log_loss_overall: float | None = None
    calibration: list[CalibrationBucket] = Field(default_factory=list)
    by_market: list[MarketTechnicalBreakdown] = Field(default_factory=list)


class ForwardSummaryResponse(BaseModel):
    counts: ForwardSummaryCounts
    results: ForwardResultCounts
    paper_test: PaperTestSummary
    technical: ForwardTechnicalSummary


class PredictionListItem(BaseModel):
    prediction_id: str
    registered_at: datetime
    tour: str
    tournament: str | None = None
    player: str | None = None
    opponent: str | None = None
    market: str
    side: str
    line: float
    decimal_odds: float
    classification: str
    settlement: str
    settlement_reason: str | None = None


class PredictionListResponse(BaseModel):
    items: list[PredictionListItem]
    total: int
    limit: int
    offset: int


class OddsHistory(BaseModel):
    """Espelha `src.forward.odds_snapshots.summarize_odds_movement` --
    "closing_odds_observed" nunca e o fechamento oficial da casa (mesma
    ressalva do item 6 da Fase 11), so a ultima leitura manual disponivel."""

    n_snapshots: int
    first_observed_odds: float | None = None
    last_observed_odds: float | None = None
    best_observed_odds: float | None = None
    closing_odds_observed: float | None = None
    closing_odds_note: str | None = None


class ClvInfo(BaseModel):
    """CLV nunca e interpretado como prova de lucratividade (item 10 da
    Fase 11) -- so o percentual/diferenca de probabilidade implicita,
    lidos de `clv_analysis.parquet`."""

    clv_pct: float | None = None
    clv_probability_diff: float | None = None


class PredictionTechnicalDetails(BaseModel):
    implied_probability: float | None = None
    model_edge: float | None = None
    sample_quality: str | None = None
    method_selected: str | None = None
    restricted: bool = False
    restricted_motivo: str | None = None
    staleness_bucket: str | None = None
    data_staleness_days: int | float | None = None
    historical_data_cutoff: str | None = None
    reasons: list[str] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)


class PredictionDetailResponse(BaseModel):
    prediction_id: str
    registered_at: datetime
    tour: str
    tournament: str | None = None
    match_id: str
    player: str | None = None
    opponent: str | None = None
    surface_ctx: str | None = None
    market: str
    side: str
    line: float

    operational_probability: float | None = None
    fair_odds: float | None = None
    minimum_odds: float | None = None
    decimal_odds: float
    bookmaker: str

    classification: str
    settlement: str
    settlement_reason: str | None = None
    settled_at: datetime | None = None

    paper_result_units: float | None = None
    paper_test_label: str | None = None

    odds_history: OddsHistory | None = None
    clv: ClvInfo | None = None
    technical: PredictionTechnicalDetails


class RegisterForwardRequest(BaseModel):
    """Chave natural (Fase 9/10) da oportunidade a registrar -- espelha
    `EvaluatedMarketResult.forward_key` do LOTE G, nunca um novo formato."""

    bookmaker: str
    tour: str
    match_id: str
    market: str
    player: str | None = None
    side: str
    line: float
    decimal_odds: float
    collected_at: str


RegisterStatus = Literal["registered", "already_registered", "not_found", "rejected_overwrite_attempt"]


class RegisterForwardResponse(BaseModel):
    status: RegisterStatus
    prediction_id: str | None = None
    message: str
