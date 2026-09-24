"""Configuracao da Fase 8 - radar diario de partidas futuras.

Reaproveita integralmente as decisoes ja tomadas nas Fases 3 a 7: nao
reajusta nenhum modelo de contagem (lambda continua sendo a mesma formula
Serve x Return da Fase 4, so aplicada a uma partida sem resultado ainda),
nao re-seleciona mercado/variante/janela (Fase 5), nao re-decide metodo de
calibracao (Fase 6.1) nem formula de odd justa/minima (Fase 7) -- so
reaplica esses componentes a uma partida futura. O unico trabalho
genuinamente novo desta fase e: ingestao de partidas futuras, resolucao de
identidade de jogador, e a "costura" ponta a ponta desses componentes ja
existentes e testados.

Ver docs/013_RADAR_DIARIO_FASE8.md secao 1 para o registro completo da
investigacao de fontes de partidas futuras (por que a ingestao e baseada em
arquivo bruto local, nao em um cliente HTTP automatizado).
"""

from __future__ import annotations

from pathlib import Path

from src.probabilistic.config import MARKETS, TOURS  # noqa: F401 - reaproveitado, nao redefinido
from src.recalibration.config import CALIBRATION_TRAIN_FOLDS, MIN_CALIBRATOR_TRAIN_N  # noqa: F401
from src.pricing.config import EDGE_LEVELS, EXTREME_PROBABILITY_THRESHOLD  # noqa: F401

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
DATA_RAW = DATA_ROOT / "raw"
DATA_PROCESSED = DATA_ROOT / "processed"
DATA_OUTPUTS = DATA_ROOT / "outputs"

PHASE8_RAW_DIR = DATA_RAW / "phase8"
PHASE8_DIR = DATA_OUTPUTS / "phase8"

PHASE4_METRICS_DIR = DATA_OUTPUTS / "phase4" / "metrics"
PHASE5_DIR = DATA_OUTPUTS / "phase5"
PHASE6_DIR = DATA_OUTPUTS / "phase6"
PHASE6_1_DIR = DATA_OUTPUTS / "phase6_1"

COUNT_DISTRIBUTION_METRICS_PATH = PHASE4_METRICS_DIR / "count_distribution_metrics.csv"
PHASE6_PREDICTIONS_PATH = PHASE6_DIR / "previsoes_por_linha.parquet"
PHASE6_1_METHOD_PATH = PHASE6_1_DIR / "selecao_metodo_por_mercado.csv"

# a data de hoje (ver phase8_summary.json, calculado em tempo de execucao a
# partir de collected_at) cai dentro da janela de teste deste fold (ver
# src/baselines/config.py FOLDS: fold_2026 = teste 2026-01-01..2026-12-31).
# O negbin_r e o calibrador aplicados a uma partida futura sao exatamente os
# que a Fase 4/6.1 ja calcularam PARA ESSE fold (treinados so com dados
# <= 2025-12-31 -- sem vazamento em relacao a uma previsao feita em
# setembro de 2026). Ver docs/013 secao 3.
CURRENT_FOLD = "fold_2026"

# rotulo de "fold" usado nas tabelas de preco desta fase (distinto de
# fold_2024/2025/2026, que sao periodos de AVALIACAO historica) -- deixa
# explicito que estas linhas nao vem de nenhum periodo de teste ja
# observado, mesmo reaproveitando os parametros do fold_2026.
RADAR_FOLD_LABEL = "radar_atual"

REQUIRED_RAW_COLUMNS = [
    "source_url", "collected_at", "tour", "tournament", "surface",
    "match_date", "round", "player_a_raw", "player_b_raw",
]

RESOLUTION_METHODS = ["exact", "alias", "fuzzy_review", "unresolved"]

# difflib.SequenceMatcher.ratio() minimo para considerar um candidato
# "aproximado" (item 2: fuzzy_review) em vez de descartar direto como
# unresolved. Limiar conservador, fixado a priori (nao ajustado nos dados
# desta fase) -- evita casar jogadores de sobrenomes parecidos mas
# diferentes.
FUZZY_MATCH_MIN_RATIO = 0.87

# item 6 (radar resumido) -- criterios de "CANDIDATO PARA CONFERIR ODDS",
# fixados a priori e documentados em docs/013 secao 7. Nao usa a palavra
# "value bet" (instrucao item 7).
CANDIDATE_LABEL = "CANDIDATO PARA CONFERIR ODDS"
CANDIDATE_SAMPLE_BUCKETS_OK = ["medium_10_49", "large_50_plus"]

RANDOM_SEED = 20260922

# Overrides mínimos e explícitos para identidades duplicadas na base canônica.
# Usar somente quando a evidência local comprovar que mais de um player_id
# representa o mesmo nome e apenas um deles possui o histórico usado pelo modelo.
# Chave: (TOUR, nome normalizado) -> player_id canônico escolhido.
PLAYER_IDENTITY_OVERRIDES = {
    ("ATP", "jakub mensik"): "ATP-210150",
}
