"""Configuracao da Fase 6 - distribuicoes probabilisticas e calibracao.

Le exclusivamente:
  - data/outputs/phase4/predictions/*.parquet (previsoes pontuais point-in-time
    ja geradas na Fase 4, por linha/jogador/partida, fora da amostra);
  - data/outputs/phase4/metrics/count_distribution_metrics.csv (media/variancia
    do alvo REAL e o parametro de dispersao `r` da Negative Binomial, ja
    ajustados na Fase 4 usando SOMENTE o fold de TREINO -- reaproveitados aqui,
    nao reajustados);
  - data/outputs/phase5/*.csv (mercados candidatos e a "melhor abordagem"
    ja identificada por mercado/tour).

Nao le data/processed/ nem data/raw/. Nao treina nenhum modelo novo: apenas
transforma a previsao pontual (lambda) + a dispersao (r) ja existentes em uma
distribuicao de probabilidade avaliada em varias linhas .5, em vez de um
unico limiar (a mediana do treino, como a Fase 4 fez). Ver docs/010 secao 0.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_OUTPUTS = PROJECT_ROOT / "data" / "outputs"

PHASE4_DIR = DATA_OUTPUTS / "phase4"
PHASE4_PREDICTIONS_DIR = PHASE4_DIR / "predictions"
PHASE4_METRICS_DIR = PHASE4_DIR / "metrics"

PHASE5_DIR = DATA_OUTPUTS / "phase5"

PHASE6_DIR = DATA_OUTPUTS / "phase6"

FOLDS = ["fold_2024", "fold_2025", "fold_2026"]
TOURS = ["ATP", "WTA"]

# mercados desta fase (instrucao do usuario -- nao incluir games/sets/tiebreak).
MARKETS = ["aces_player", "total_aces_match", "double_faults_player"]

ACTUAL_COL = {
    "aces_player": "target_aces",
    "total_aces_match": "target_total_aces_match",
    "double_faults_player": "target_double_faults",
}
PRED_PREFIX = {
    "aces_player": "pred_aces",
    "total_aces_match": "pred_total_aces",
    "double_faults_player": "pred_double_faults",
}

SURFACES = ["Hard", "Clay", "Grass"]


def pred_column_name(market: str, variant: str, window: str) -> str:
    """Nome da coluna de previsao pontual na Fase 4. double_faults_player e
    um caso especial: a Fase 4 so modelou a variante isolada para esse
    mercado (nunca existiu Serve x Return de double faults -- ver
    src/baselines/rate_models.py add_double_fault_predictions), entao a
    coluna nao carrega o token de variante (`pred_double_faults_{window}`,
    nao `pred_double_faults_isolated_{window}`)."""

    if market == "double_faults_player":
        return f"{PRED_PREFIX[market]}_{window}"
    return f"{PRED_PREFIX[market]}_{variant}_{window}"

# quantis usados para derivar a faixa historica de linhas .5 a partir da
# distribuicao AJUSTADA NO TREINO (media/variancia de count_distribution_metrics
# .csv) de cada mercado/tour/fold -- "nao fixar limites arbitrarios" (item 5).
LINE_GRID_LOW_Q = 0.01
LINE_GRID_HIGH_Q = 0.99
MAX_LINES_PER_GROUP = 14  # teto de seguranca contra faixas patologicamente largas

# buckets de "dificuldade da linha" (item 7), relativos ao z-score
# (linha - lambda) / desvio_padrao_implicito_do_modelo, calculados por LINHA
# (nao por mercado inteiro) -- definidos a priori.
LINE_DIFFICULTY_BUCKETS = [
    (-float("inf"), -1.0, "muito_abaixo_da_media"),
    (-1.0, 1.0, "proxima_da_media"),
    (1.0, float("inf"), "muito_acima_da_media"),
]

# reaproveita os buckets de tamanho de historico ja definidos na Fase 4
# (mesmas faixas, mesmo criterio -- item 9/10 desta fase).
from src.baselines.config import SAMPLE_SIZE_BUCKETS  # noqa: E402,F401

# limiar de "ganho material" (item 4: total de aces, independencia vs ajuste
# empirico) -- mesmo espirito do limiar de 3% ja usado na Fase 5
# (src/selection/config.py MIN_MEAN_DELTA_REL), reaproveitado aqui para nao
# inventar um segundo criterio arbitrario.
MIN_BRIER_GAIN_REL_FOR_DEPENDENCY_ADJUSTMENT = 0.03

RANDOM_SEED = 20260922
