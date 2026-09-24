// Espelha api/schemas/common.py (LOTE A) -- nunca inventa campo que a API
// nao devolva; historical_data_cutoff eh explicitamente nulavel porque o
// backend tambem pode devolver null (base indisponivel no ambiente).

export interface HealthResponse {
  status: "ok";
  app: string;
}

export interface InfoResponse {
  app: string;
  api_version: string;
  timezone: string;
  default_bookmaker: string;
  historical_data_cutoff: string | null;
  forward_version_id: string;
}

// Espelha api/schemas/calendar.py (LOTE C). event_datetime_original/utc/
// sao_paulo trafegam como string ISO 8601 (a API ja resolve o fuso via
// zoneinfo -- o frontend nunca recalcula, so formata para exibicao).
export type Tour = "ATP" | "WTA";
export type Surface = "Hard" | "Clay" | "Grass";
export type MatchStatus = "futuro" | "proximo" | "iniciado" | "encerrado";

export interface MatchSchedule {
  match_key: string;
  tour: Tour;
  tournament: string;
  round: string;
  surface: Surface;
  player_a: string;
  player_b: string;
  event_datetime_original: string;
  event_timezone: string;
  event_datetime_utc: string;
  event_datetime_sao_paulo: string;
  status: MatchStatus;
  source_url: string | null;
  collected_at: string;
}

// Espelha api/schemas/radar.py (LOTE D). Uma entrada por (partida,
// mercado, jogador quando aplicavel, linha, lado) -- mesma granularidade
// de data/outputs/phase8/precos_por_linha.parquet. decision_state e um
// agrupamento de apresentacao de is_candidate/candidate_blockers (Fase 8,
// src/radar/candidates.py), nao uma nova classificacao estatistica.
export type Market = "aces_player" | "total_aces_match" | "double_faults_player";
export type Side = "over" | "under";
export type DecisionState = "CONFERIR_ODDS" | "OBSERVAR" | "DESCARTADO";

export interface RadarLine {
  match_key: string;
  match_id: string;
  tour: Tour;
  tournament: string;
  round: string;
  surface: Surface;
  player_a: string;
  player_b: string;
  event_datetime_sao_paulo: string | null;

  market: Market;
  player: string | null;
  side: Side;
  line: number;
  probability: number;
  fair_odds: number | null;
  minimum_odds: number | null;
  odd_minima_por_edge: Record<string, number | null>;

  decision_state: DecisionState;
  candidate_blockers: string[];
  sample_bucket_career: string;
  restricted: boolean;
  restricted_motivo: string | null;
  extreme_probability: boolean;
  identity_trusted: boolean;
  resolution_method_player: string | null;
  resolution_method_opponent: string | null;

  staleness_status: string | null;
  staleness_days: number | null;
  historical_data_cutoff: string | null;

  // LOTE J — Overlay Tennis Abstract
  effective_data_cutoff?: string | null;
  overlay_status?: string | null;
}

// Espelha api/schemas/screenshots.py (LOTE E). ScreenshotUploadResponse
// nunca inclui stored_path/sha256 -- so o que a tela ENVIAR PRINT precisa
// mostrar apos o envio.
export type TabType = "ACES" | "GAMES_TOTALS";

export interface ScreenshotUploadResponse {
  upload_id: string;
  match_key: string;
  tab_type: TabType;
  bookmaker: string;
  created_at: string;
  mime_type: string;
  file_size: number;
}

// Espelha api/schemas/screenshots.py (LOTE F). ExtractionMarket e distinto
// de `Market` (radar, LOTE D): sao mercados da LEITURA do print (o que a
// casa exibe), nao os mercados que o modelo estatistico calcula --
// "total_games" existe aqui mas nao e um Market do radar (docs/018 secao
// 6.3.1: ainda nao modelado). `side` e "Over"/"Under" (texto da casa),
// deliberadamente diferente do "over"/"under" minusculo de RadarLine.
export type ExtractionMarket = "aces_player" | "total_aces_match" | "total_games";
export type ExtractionSide = "Over" | "Under";
export type ExtractionStatus = "AUTO_VALIDATED" | "NEEDS_CONFIRMATION";

export interface NormalizedMarket {
  market: ExtractionMarket;
  player: string | null;
  bookmaker_display: string;
  side: ExtractionSide | null;
  model_line: number | null;
  decimal_odds: number;
  confidence: number | null;
  warnings: string[];
  needs_confirmation: boolean;
}

export interface ExtractionResponse {
  extraction_id: string;
  upload_id: string;
  match_key: string;
  tab_type: TabType;
  status: ExtractionStatus;
  provider: string;
  provider_model: string | null;
  created_at: string;
  markets: NormalizedMarket[];
  extraction_warnings: string[];
}

export interface ConfirmMarketInput {
  market: ExtractionMarket;
  player: string | null;
  bookmaker_display: string;
  decimal_odds: number;
}

export interface ConfirmResponse {
  extraction_id: string;
  upload_id: string;
  match_key: string;
  tab_type: TabType;
  confirmed_at: string;
  confirmed_by: string;
  corrected: boolean;
  markets: NormalizedMarket[];
}

// Espelha api/schemas/odds_evaluation.py (LOTE G). `evaluation_label` e um
// AGRUPAMENTO VISUAL do `decision_state` ja calculado pela Fase 10 (nunca
// uma nova classificacao) -- ver docs/018 secao 6.6. Nenhum campo numerico
// aqui e recalculado no frontend: `model_probability`/`fair_odds`/
// `minimum_odds`/`decision_state` vem prontos da API.
export type EvaluationLabel = "PASSOU_DO_LIMITE" | "OBSERVAR" | "NAO_PASSOU" | "SEM_AVALIACAO_DISPONIVEL";

export interface TechnicalDetails {
  implied_probability: number | null;
  model_edge: number | null;
  sample_quality: string | null;
  matched: boolean | null;
  match_reason: string | null;
  data_staleness_days: number | null;
  restricted_motivo: string | null;
}

// Espelha api/schemas/odds_evaluation.py::ForwardKey (LOTE H) -- chave
// natural (Fase 9/10) usada so para o botao "Registrar no Forward Test"
// identificar a oportunidade, nunca para recalcular nada no cliente.
export interface ForwardKey {
  bookmaker: string;
  tour: string;
  match_id: string;
  market: string;
  player: string | null;
  side: string;
  line: number;
  decimal_odds: number;
  collected_at: string;
}

export interface EvaluatedMarketResult {
  market: ExtractionMarket;
  player: string | null;
  bookmaker_display: string;
  model_line: number | null;
  side: ExtractionSide | null;
  bookmaker_odds: number;

  model_probability: number | null;
  fair_odds: number | null;
  minimum_odds: number | null;

  decision_state: string | null;
  evaluation_label: EvaluationLabel;
  evaluation_message: string | null;

  staleness_status: string | null;
  restricted: boolean | null;

  technical: TechnicalDetails | null;
  forward_key: ForwardKey | null;
  prediction_id: string | null;
  already_registered_forward_test: boolean;
  error: string | null;
}

export interface EvaluateResponse {
  upload_id: string;
  extraction_id: string;
  match_key: string;
  confirmed_at: string;

  historical_data_cutoff: string | null;
  data_staleness_days: number | null;
  staleness_warning: string | null;

  results: EvaluatedMarketResult[];
}

// Espelha api/schemas/forward.py (LOTE H) -- leitura do Forward Test
// (Fase 11) ja calculado; nenhum campo aqui e recalculado no cliente.
export interface ForwardSummaryCounts {
  n_predictions_registered: number;
  n_pending_settlement: number;
  n_resolved: number;
  n_candidates: number;
  n_observar: number;
  n_descartados: number;
}

export interface ForwardResultCounts {
  wins: number;
  losses: number;
  void: number;
  pending: number;
}

export interface PaperTestSummary {
  label: string;
  n_entries_simulated: number;
  n_wins: number | null;
  n_losses: number | null;
  n_voids: number | null;
  n_pending_settlement: number | null;
  total_staked_units: number | null;
  total_pnl_units: number | null;
  roi: number | null;
  max_drawdown_units: number | null;
  max_consecutive_losses: number | null;
  outcome_distribution: Record<string, number> | null;
}

export interface CalibrationBucket {
  bucket: string;
  n: number;
  mean_predicted: number | null;
  observed_rate: number | null;
}

export interface MarketTechnicalBreakdown {
  market: string;
  n: number;
  brier_score: number | null;
  clv_avg_pct: number | null;
  paper_roi: number | null;
}

export interface ForwardTechnicalSummary {
  brier_score_overall: number | null;
  log_loss_overall: number | null;
  calibration: CalibrationBucket[];
  by_market: MarketTechnicalBreakdown[];
}

export interface ForwardSummaryResponse {
  counts: ForwardSummaryCounts;
  results: ForwardResultCounts;
  paper_test: PaperTestSummary;
  technical: ForwardTechnicalSummary;
}

export interface PredictionListItem {
  prediction_id: string;
  registered_at: string;
  tour: string;
  tournament: string | null;
  player: string | null;
  opponent: string | null;
  market: string;
  side: string;
  line: number;
  decimal_odds: number;
  classification: string;
  settlement: string;
  settlement_reason: string | null;
}

export interface PredictionListResponse {
  items: PredictionListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface OddsHistory {
  n_snapshots: number;
  first_observed_odds: number | null;
  last_observed_odds: number | null;
  best_observed_odds: number | null;
  closing_odds_observed: number | null;
  closing_odds_note: string | null;
}

export interface ClvInfo {
  clv_pct: number | null;
  clv_probability_diff: number | null;
}

export interface PredictionTechnicalDetails {
  implied_probability: number | null;
  model_edge: number | null;
  sample_quality: string | null;
  method_selected: string | null;
  restricted: boolean;
  restricted_motivo: string | null;
  staleness_bucket: string | null;
  data_staleness_days: number | null;
  historical_data_cutoff: string | null;
  reasons: string[];
  alerts: string[];
}

export interface PredictionDetailResponse {
  prediction_id: string;
  registered_at: string;
  tour: string;
  tournament: string | null;
  match_id: string;
  player: string | null;
  opponent: string | null;
  surface_ctx: string | null;
  market: string;
  side: string;
  line: number;

  operational_probability: number | null;
  fair_odds: number | null;
  minimum_odds: number | null;
  decimal_odds: number;
  bookmaker: string;

  classification: string;
  settlement: string;
  settlement_reason: string | null;
  settled_at: string | null;

  paper_result_units: number | null;
  paper_test_label: string | null;

  odds_history: OddsHistory | null;
  clv: ClvInfo | null;
  technical: PredictionTechnicalDetails;
}

export interface RegisterForwardRequest {
  bookmaker: string;
  tour: string;
  match_id: string;
  market: string;
  player: string | null;
  side: string;
  line: number;
  decimal_odds: number;
  collected_at: string;
}

export type RegisterForwardStatus = "registered" | "already_registered" | "not_found" | "rejected_overwrite_attempt";

export interface RegisterForwardResponse {
  status: RegisterForwardStatus;
  prediction_id: string | null;
  message: string;
}
