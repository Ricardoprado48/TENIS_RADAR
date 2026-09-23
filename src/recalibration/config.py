"""Configuracao da Fase 6.1 - calibracao das probabilidades out-of-sample da
Fase 6 (item 0: "nao altere os modelos de previsao de contagem da Fase 6").

Le exclusivamente data/outputs/phase6/previsoes_por_linha.parquet (a
probabilidade Negative Binomial ja calculada na Fase 6 -- `p_over_negbin` --
e o resultado real -- `actual_over`). Nao le data/processed/ nem
data/raw/. Nao recalcula lambda nem `r`.

Regra anti-leakage temporal (item 3): o calibrador de cada fold de avaliacao
so pode ser ajustado com dados de folds ANTERIORES (mesma logica de janela
expansiva ja usada em toda a Fase 4/6 -- src/baselines/walkforward.py). O
fold_2024 nao tem nenhum fold anterior disponivel nos dados (a cobertura
comeca em 2022, mas o primeiro fold de AVALIACAO ja e 2024) -- portanto
fold_2024 NUNCA e calibrado nesta fase; suas probabilidades permanecem
exatamente as brutas da Fase 6, com o metodo marcado explicitamente como
"sem_periodo_anterior" (nunca substituidas silenciosamente, item 11).
"""

from __future__ import annotations

from pathlib import Path

from src.probabilistic.config import MARKETS, TOURS  # noqa: F401

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_OUTPUTS = PROJECT_ROOT / "data" / "outputs"

PHASE6_DIR = DATA_OUTPUTS / "phase6"
PHASE6_PREDICTIONS_PATH = PHASE6_DIR / "previsoes_por_linha.parquet"

PHASE6_1_DIR = DATA_OUTPUTS / "phase6_1"

FOLDS = ["fold_2024", "fold_2025", "fold_2026"]

# calibracao temporal expansiva (item 3): cada fold de AVALIACAO usa somente
# folds estritamente anteriores para treinar o calibrador. fold_2024 fica de
# fora do dict de proposito -- nao tem fold anterior, entao nunca e
# calibrado (ver docstring do modulo).
CALIBRATION_TRAIN_FOLDS = {
    "fold_2025": ["fold_2024"],
    "fold_2026": ["fold_2024", "fold_2025"],
}
EVALUABLE_FOLDS = list(CALIBRATION_TRAIN_FOLDS.keys())
NO_PRIOR_PERIOD_FOLDS = [f for f in FOLDS if f not in CALIBRATION_TRAIN_FOLDS]

RAW_PROB_COL = "p_over_negbin"
ACTUAL_COL = "actual_over"

METHODS = ["raw", "platt", "isotonic"]

# faixas de probabilidade exigidas explicitamente no item 5 (fixadas a
# priori, iguais para todos os mercados/tours).
PROB_BUCKET_EDGES = [0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
PROB_BUCKET_LABELS = ["<20%", "20-30%", "30-40%", "40-50%", "50-60%",
                       "60-70%", "70-80%", "80-90%", "90%+"]

# amostra minima para reportar um bucket com confianca (item 5: "marcar
# explicitamente" quando insuficiente) -- limiar fixado a priori, mesma
# ordem de grandeza do MIN_COVERAGE_N ja usado na Fase 5
# (src/selection/config.py).
MIN_BUCKET_N_FOR_REPORT = 100

# amostra minima para AJUSTAR qualquer calibrador (item 12: "fallback seguro
# quando nao houver amostra suficiente") -- abaixo disso, a probabilidade
# bruta e mantida e o metodo e marcado como "raw_amostra_insuficiente".
MIN_CALIBRATOR_TRAIN_N = 500

# criterio de selecao (item 9): um metodo so substitui o raw se melhorar
# Brier E ECE nos DOIS folds avaliaveis (nao so no agregado) -- evita
# escolher por um ganho medio que depende de um unico fold.
REQUIRE_IMPROVEMENT_IN_ALL_EVALUABLE_FOLDS = True
MIN_REL_BRIER_IMPROVEMENT = 0.01  # 1% -- mesma ordem de grandeza dos
# limiares "de fold forte" ja usados na Fase 5 (MIN_PER_FOLD_DELTA_REL_FOR_STRONG_WIN)

RANDOM_SEED = 20260922
