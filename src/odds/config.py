"""Configuracao da Fase 9 - coleta pontual de odds e comparacao com o radar.

Le exclusivamente:
  - data/outputs/phase8/precos_por_linha.parquet (probabilidade operacional,
    odd justa e todas as flags de qualidade ja calculadas na Fase 8 -- nao
    recalculado aqui);
  - data/outputs/phase8/radar_diario_resumo.csv (contexto de partida por
    match_id);
  - data/processed/{tour}/matches.parquet (somente para o `max()` de
    `tournament_date`, usado exclusivamente para o aviso de defasagem do item
    10 -- nenhuma feature e recalculada a partir daqui).

Nao re-treina, nao recalibra e nao re-seleciona mercado/variante/janela --
apenas registra uma odd observada e a compara com o que a Fase 7/8 ja
decidiu. `bookmaker` e um campo generico (item 2): Betano e a primeira casa
usada, mas nenhuma parte deste modulo assume que ela e a unica.
"""

from __future__ import annotations

from pathlib import Path

from src.probabilistic.config import MARKETS, TOURS  # noqa: F401 - reaproveitado
from src.pricing.config import EDGE_LEVELS  # noqa: F401 - reaproveitado, nao redefinido

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
DATA_RAW = DATA_ROOT / "raw"
DATA_PROCESSED = DATA_ROOT / "processed"
DATA_OUTPUTS = DATA_ROOT / "outputs"

# radar "atual" para conferir odds: a Fase 8.1 confirmou que a base
# atualizada e byte-a-byte identica a Fase 8 original (0/1972 linhas
# mudaram, docs/014 secao 8), entao a Fase 8 original ja e a fonte correta e
# mais simples -- nenhuma duplicacao de dado foi criada so para esta fase.
PHASE8_DIR = DATA_OUTPUTS / "phase8"
PHASE8_PRICES_PATH = PHASE8_DIR / "precos_por_linha.parquet"
PHASE8_SUMMARY_PATH = PHASE8_DIR / "radar_diario_resumo.csv"

PHASE9_DIR = DATA_OUTPUTS / "phase9"
BETANO_INVESTIGATION_DIR = DATA_RAW / "phase9_betano"

ODDS_OBSERVED_PATH = PHASE9_DIR / "odds_observed.parquet"
COMPARISON_PATH = PHASE9_DIR / "comparison_with_model.parquet"
DAILY_CHECK_PATH = PHASE9_DIR / "daily_odds_check.csv"
SNAPSHOTS_HISTORY_PATH = PHASE9_DIR / "snapshots_history.parquet"

# item 2: arquitetura generica de bookmaker; Betano e so a primeira casa
# usada operacionalmente (nao ha lista fechada de casas suportadas).
DEFAULT_BOOKMAKER = "Betano"

SIDES = ["over", "under"]

# item 9: rotulos objetivos de classificacao (nunca "aposta garantida"/
# "aposta certa"/"lucro garantido" -- proibido pela instrucao).
STATUS_BELOW_THRESHOLD = "ABAIXO_DO_LIMITE"
EDGE_STATUS_LABELS = {
    "2pct": "ATINGE_EDGE_2",
    "3pct": "ATINGE_EDGE_3",
    "5pct": "ATINGE_EDGE_5",
    "7_5pct": "ATINGE_EDGE_7_5",
    "10pct": "ATINGE_EDGE_10",
}

# item 5: escopo da consulta -- soh os 3 mercados ja aprovados/gerados pela
# Fase 5/6/7/8 (nao existe odd de games/sets/tiebreak nesta base).
ALLOWED_MARKETS = list(MARKETS)

# colunas exigidas de uma observacao de odd (item 6), na ordem da instrucao.
OBSERVATION_COLUMNS = [
    "bookmaker", "match_id", "tour", "tournament", "player", "opponent",
    "market", "side", "line", "decimal_odds", "collected_at",
    "source_method", "source_url",
]

RANDOM_SEED = 20260922
