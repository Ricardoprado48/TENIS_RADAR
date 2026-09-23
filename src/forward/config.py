"""Configuracao da Fase 11 - forward test operacional e registro prospectivo.

Le exclusivamente:
  - data/outputs/phase10/opportunities_evaluated.parquet (classificacao,
    motivos, alertas e metricas ja calculadas pela Fase 10 -- nao
    recalculado aqui);
  - data/outputs/phase9/odds_observed.parquet (torneio/adversario, so para
    completar o registro pre-jogo do item 3 -- Fase 9, nao recalculado).

Nao re-treina, nao recalibra, nao re-seleciona mercado e nao altera nenhuma
probabilidade/odd/edge/classificacao ja calculada nas Fases 7-10. O trabalho
desta fase e registrar prospectivamente essas decisoes, coletar snapshots de
odds adicionais, e comparar contra o resultado real quando disponivel --
sempre append-only.
"""

from __future__ import annotations

from pathlib import Path

from src.decision.config import EDGE_RANK  # noqa: F401 - reaproveitado, nao redefinido

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_OUTPUTS = PROJECT_ROOT / "data" / "outputs"

PHASE9_DIR = DATA_OUTPUTS / "phase9"
PHASE9_OBSERVATIONS_PATH = PHASE9_DIR / "odds_observed.parquet"

PHASE10_DIR = DATA_OUTPUTS / "phase10"
PHASE10_OPPORTUNITIES_PATH = PHASE10_DIR / "opportunities_evaluated.parquet"

PHASE11_DIR = DATA_OUTPUTS / "phase11"
FORWARD_PREDICTIONS_PATH = PHASE11_DIR / "forward_predictions.parquet"
ODDS_SNAPSHOTS_PATH = PHASE11_DIR / "odds_snapshots.parquet"
RESULTS_PATH = PHASE11_DIR / "results.parquet"
SETTLEMENTS_PATH = PHASE11_DIR / "settlements.parquet"
FORWARD_METRICS_PATH = PHASE11_DIR / "forward_metrics.parquet"
PAPER_TEST_PATH = PHASE11_DIR / "paper_test.parquet"
CLV_ANALYSIS_PATH = PHASE11_DIR / "clv_analysis.parquet"
PHASE11_SUMMARY_PATH = PHASE11_DIR / "phase11_summary.json"

# ---------------------------------------------------------------------------
# item 2: congelamento de versao operacional. Mudar qualquer regra/feature/
# calibrador das fases anteriores exige uma NOVA string aqui -- nunca
# reescrever um registro ja gravado com a versao antiga (item 1).
# ---------------------------------------------------------------------------
FORWARD_VERSION_ID = "TENNIS_RADAR_V1_FORWARD"
# motor de features Serve x Return (Fase 3), inalterado desde entao.
FEATURES_VERSION = "FASE3_SERVE_RETURN_V1"
# calibrador Platt/Isotonic selecionado por segmento (Fase 6.1, docs/011).
CALIBRATION_VERSION = "FASE6_1_PLATT_ISOTONIC_V1"
# regras operacionais de classificacao (Fase 10, docs/016).
RULES_VERSION = "FASE10_V1"

# item 4: todas as classificacoes precisam ser registradas, nunca so os
# casos favoraveis.
ALL_CLASSIFICATIONS = [
    "DESCARTAR", "OBSERVAR", "CANDIDATO_FRACO", "CANDIDATO", "CANDIDATO_FORTE",
]
# item 11: o paper test so simula oportunidades "elegiveis" -- DESCARTAR ja
# foi reprovado por algum gate obrigatorio da Fase 10 e nunca seria de fato
# considerada operacionalmente (continua registrada em
# forward_predictions.parquet, item 4, so fica fora do P&L simulado).
PAPER_TEST_ELIGIBLE_CLASSIFICATIONS = [
    "OBSERVAR", "CANDIDATO_FRACO", "CANDIDATO", "CANDIDATO_FORTE",
]

# ---------------------------------------------------------------------------
# item 8: settlement objetivo. Retirement/walkover NUNCA recebem uma regra
# inventada -- caem em BOOKMAKER_RULE_REQUIRED ate existir regra
# documentada para a casa especifica (nenhuma foi documentada nesta fase).
# ---------------------------------------------------------------------------
SETTLEMENT_WIN = "WIN"
SETTLEMENT_LOSS = "LOSS"
SETTLEMENT_VOID = "VOID"
SETTLEMENT_UNRESOLVED = "UNRESOLVED"
SETTLEMENT_BOOKMAKER_RULE_REQUIRED = "BOOKMAKER_RULE_REQUIRED"

MATCH_STATUS_COMPLETED = "completed"
MATCH_STATUS_RETIREMENT = "retirement"
MATCH_STATUS_WALKOVER = "walkover"
VALID_MATCH_STATUSES = [MATCH_STATUS_COMPLETED, MATCH_STATUS_RETIREMENT, MATCH_STATUS_WALKOVER]

# item 11: rotulo explicito -- nunca dinheiro real, nunca Kelly, nunca
# unidades variaveis, nunca recomendacao de valor monetario.
PAPER_TEST_LABEL = "PAPER_TEST_ONLY"
PAPER_TEST_FLAT_STAKE_UNITS = 1.0

# item 12: os mesmos 5 thresholds de edge ja definidos nas Fases 7/9/10 --
# nenhum escolhido aqui como padrao operacional definitivo.
EDGE_THRESHOLD_LABELS_CUMULATIVE = [
    "ATINGE_EDGE_2", "ATINGE_EDGE_3", "ATINGE_EDGE_5", "ATINGE_EDGE_7_5", "ATINGE_EDGE_10",
]

# item 15: checkpoints SOMENTE descritivos para relatorio -- nunca uma regra
# automatica de "aprovacao"/"reprovacao" do modelo baseada so na quantidade.
SAMPLE_SIZE_CHECKPOINTS = [25, 50, 100, 250, 500]

# item 9: buckets de calibracao, largura fixa, fixados a priori.
CALIBRATION_BUCKET_EDGES = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

RANDOM_SEED = 20260922
