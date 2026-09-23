"""Configuracao da Fase 7 - odd justa e odd minima aceitavel.

Le exclusivamente:
  - data/outputs/phase6/previsoes_por_linha.parquet (contexto: linha,
    superficie, tamanho de historico, dificuldade da linha -- Fase 6, nao
    recalculado aqui);
  - data/outputs/phase6_1/previsoes_calibradas.parquet (probabilidade
    operacional ja definida na Fase 6.1: calibrada quando o calibrador foi
    aprovado, bruta quando a recalibracao nao trouxe ganho -- Fase 6.1, nao
    recalculado aqui).

Nao le data/processed/ nem data/raw/. Nao ajusta nenhum modelo nem
calibrador novo: apenas converte probabilidade -> odd justa/minima e aplica
flags de qualidade ja documentadas nas fases anteriores.
"""

from __future__ import annotations

from pathlib import Path

from src.probabilistic.config import MARKETS, TOURS  # noqa: F401
from src.recalibration.config import MIN_CALIBRATOR_TRAIN_N  # noqa: F401

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_OUTPUTS = PROJECT_ROOT / "data" / "outputs"

PHASE6_DIR = DATA_OUTPUTS / "phase6"
PHASE6_PREDICTIONS_PATH = PHASE6_DIR / "previsoes_por_linha.parquet"

PHASE6_1_DIR = DATA_OUTPUTS / "phase6_1"
PHASE6_1_PREDICTIONS_PATH = PHASE6_1_DIR / "previsoes_calibradas.parquet"

PHASE7_DIR = DATA_OUTPUTS / "phase7"

SIDES = ["over", "under"]

# chaves de juncao entre Fase 6 (contexto) e Fase 6.1 (probabilidade
# operacional) -- ambos os parquets tem exatamente as mesmas 1.036.994
# linhas, 1:1, verificado antes de escrever este modulo.
JOIN_KEYS = ["tour", "market", "fold", "match_id", "player_id", "line"]

# cenarios de edge minimo a comparar (item 3) -- nao escolhemos um padrao
# operacional nesta fase (item 10), so geramos as faixas.
EDGE_LEVELS = [
    ("2pct", 0.02),
    ("3pct", 0.03),
    ("5pct", 0.05),
    ("7_5pct", 0.075),
    ("10pct", 0.10),
]

# probabilidade >= 90% exige cautela extra (item 6) -- mesmo limiar usado
# como "banda 90%+" na Fase 6.1 (PROB_BUCKET_EDGES), reaproveitado aqui.
EXTREME_PROBABILITY_THRESHOLD = 0.90

# segmentos com restricao documentada (item 6): ATP aces_player em Grass.
# Fixado a priori a partir da classificacao objetiva ja publicada na Fase
# 6.1 (docs/011_CALIBRACAO_PROBABILISTICA_FASE6_1.md, secao 15 -- "USAR COM
# RESTRICAO"): o ECE piora de 0,031 para 0,039 especificamente em Grass
# apos a calibracao Platt (n=7.966 no fold avaliado), enquanto Hard/Clay
# (~90% da amostra) nao apresentam essa ressalva. Nao recalculado aqui --
# reaproveita a decisao ja tomada e documentada na fase anterior.
RESTRICTED_SEGMENTS = [
    {
        "tour": "ATP", "market": "aces_player", "surface": "Grass",
        "motivo": (
            "Fase 6.1 (docs/011, secao 15, classificacao 'USAR COM RESTRICAO'): "
            "ECE piora de 0,031 para 0,039 apos calibracao Platt especificamente "
            "em Grass (n=7.966 no fold avaliado); Hard/Clay (~90% da amostra) "
            "sem ressalva."
        ),
    },
]

# classificacao completa da Fase 6.1 (docs/011, secao 15), reproduzida aqui
# somente para referencia/relatorio -- nao usada para alterar nenhum calculo
# alem da flag de restricao acima.
PHASE6_1_CLASSIFICATION = {
    ("ATP", "aces_player"): "USAR COM RESTRICAO",
    ("ATP", "total_aces_match"): "PRONTO PARA ODDS",
    ("ATP", "double_faults_player"): "PRONTO PARA ODDS",
    ("WTA", "aces_player"): "PRONTO PARA ODDS",
    ("WTA", "total_aces_match"): "PRONTO PARA ODDS",
    ("WTA", "double_faults_player"): "PRONTO PARA ODDS",
}

RANDOM_SEED = 20260922
