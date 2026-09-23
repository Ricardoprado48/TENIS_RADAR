"""Configuracao da Fase 4 - baselines estatisticos e avaliacao walk-forward.

Le exclusivamente as features point-in-time ja geradas em
data/processed/features/ (Fase 3, nunca recalculadas aqui). A UNICA leitura
fora de data/processed/features/ e um join pontual em
data/processed/{tour}/matches.parquet para trazer 2 colunas de RESULTADO
REAL da propria partida (aces, double_faults) que servem de rotulo
("y_true") na avaliacao -- nunca como preditor. Ver docs/008 secao 2 para a
justificativa dessa decisao (o rotulo de avaliacao nao pode vir da Fase 3
por desenho: a Fase 3 exclui deliberadamente as estatisticas da propria
partida das features, para nao vazar). Nao escreve nada em data/processed/.
"""

from pathlib import Path

from src.normalization.config import PROCESSED_DIRS, TOURS  # noqa: F401

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_OUTPUTS = PROJECT_ROOT / "data" / "outputs"
PHASE4_DIR = DATA_OUTPUTS / "phase4"
PHASE4_PREDICTIONS_DIR = PHASE4_DIR / "predictions"
PHASE4_METRICS_DIR = PHASE4_DIR / "metrics"
PHASE4_CONFIG_DIR = PHASE4_DIR / "config"

# Janelas historicas a comparar (item 7). Mesmos nomes materializados na
# Fase 3 (src/features/profile.py ALL_WINDOW_NAMES) -- nao adicionamos nem
# escolhemos nenhuma aqui, so reaproveitamos.
WINDOWS = ["career", "last10", "last20", "last50", "last365d", "surface_career", "decay90d"]

# janela usada como "principal" quando um numero precisa ser escolhido para
# tabelas resumidas (nao e uma conclusao de "melhor janela" -- e so o ponto
# de partida citado explicitamente no exemplo do CLAUDE.md #5/#18: Ace Rate
# do sacador). A comparacao completa entre todas as WINDOWS acontece em
# separado (item 7) e decide objetivamente qual e mais estavel.
DEFAULT_WINDOW = "career"

# folds walk-forward (item 4 da instrucao): janela de treino expansiva,
# teste sempre no ano seguinte. Os dados da Fase 1/2/3 cobrem 2022-01-03 a
# 2026-05-25 (verificado antes de definir os folds) -- os 3 folds abaixo
# reproduzem exatamente o exemplo do enunciado (2022-2023->2024,
# 2022-2024->2025, 2022-2025->2026) porque coincidem com a cobertura real
# dos dados; o fold de 2026 e necessariamente parcial (so ate maio).
FOLDS = [
    {"name": "fold_2024", "train_end": "2023-12-31", "test_start": "2024-01-01", "test_end": "2024-12-31"},
    {"name": "fold_2025", "train_end": "2024-12-31", "test_start": "2025-01-01", "test_end": "2025-12-31"},
    {"name": "fold_2026", "train_end": "2025-12-31", "test_start": "2026-01-01", "test_end": "2026-12-31"},
]

# faixas de tamanho de amostra historica (item 9 / "cold start") usadas para
# segmentar a avaliacao -- definidas a priori, nao ajustadas post-hoc.
SAMPLE_SIZE_BUCKETS = [
    (0, 0, "cold_start"),          # nenhuma partida anterior
    (1, 9, "small_1_9"),           # historico pequeno
    (10, 49, "medium_10_49"),
    (50, None, "large_50_plus"),
]

# faixas de ranking (item 6) -- definidas a priori.
RANKING_BUCKETS = [
    (1, 50, "top50"),
    (51, 100, "top51_100"),
    (101, 300, "top101_300"),
    (301, None, "outside_300"),
]

RANDOM_SEED = 20260922
