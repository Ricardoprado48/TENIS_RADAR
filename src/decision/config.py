"""Configuracao da Fase 10 - regras operacionais objetivas de classificacao.

Le exclusivamente as saidas ja calculadas pelas Fases 7/8/9:
  - data/outputs/phase9/comparison_with_model.parquet (odd observada x
    probabilidade operacional x edge x status, ja calculados na Fase 9);
  - data/outputs/phase8/precos_por_linha.parquet (contexto da linha:
    identidade, restricao, flags de qualidade, ja calculados na Fase 8);
  - data/outputs/phase8/partidas_resolvidas.parquet (para re-derivar, via o
    MESMO motor de features da Fase 3/8 -- nunca reimplementado --, os
    contadores de amostra por jogador usados na classificacao de qualidade).

Nao re-treina nenhum modelo, nao recalibra nenhuma probabilidade, nao
re-seleciona mercado/variante/janela e nao altera nenhuma formula de odd
justa/minima/edge ja definida nas Fases 7/9. O trabalho desta fase e
inteiramente uma camada de decisao determinstica sobre dados ja calculados.
"""

from __future__ import annotations

from pathlib import Path

from src.probabilistic.config import MARKETS, TOURS  # noqa: F401 - reaproveitado
from src.pricing.config import EDGE_LEVELS, EXTREME_PROBABILITY_THRESHOLD  # noqa: F401

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
DATA_OUTPUTS = DATA_ROOT / "outputs"

PHASE8_DIR = DATA_OUTPUTS / "phase8"
PHASE8_PRICES_PATH = PHASE8_DIR / "precos_por_linha.parquet"
PHASE8_RESOLVED_PATH = PHASE8_DIR / "partidas_resolvidas.parquet"

PHASE9_DIR = DATA_OUTPUTS / "phase9"
PHASE9_COMPARISON_PATH = PHASE9_DIR / "comparison_with_model.parquet"

PHASE10_DIR = DATA_OUTPUTS / "phase10"
OPPORTUNITIES_PATH = PHASE10_DIR / "opportunities_evaluated.parquet"
OPERATIONAL_RULES_PATH = PHASE10_DIR / "operational_rules.json"
CLASSIFICATION_SUMMARY_PATH = PHASE10_DIR / "classification_summary.csv"
REJECTED_PATH = PHASE10_DIR / "rejected_opportunities.csv"
PHASE10_SUMMARY_PATH = PHASE10_DIR / "phase10_summary.json"

# item 5: escopo -- so os 3 mercados ja aprovados nas Fases 5/6/7/8/9
# (nenhum mercado novo foi adicionado nesta fase).
ALLOWED_MARKETS = list(MARKETS)

_RELIABLE_RESOLUTION_METHODS = {"exact", "alias"}

# ---------------------------------------------------------------------------
# item 3: estados operacionais. Ordem "pior -> melhor" (usada so para
# ordenar relatorios). Nunca usar "aposta garantida"/"aposta segura"/
# "garantia"/"lucro garantido" para nomear ou descrever nenhum estado.
# ---------------------------------------------------------------------------
STATE_DESCARTAR = "DESCARTAR"
STATE_OBSERVAR = "OBSERVAR"
STATE_CANDIDATO_FRACO = "CANDIDATO_FRACO"
STATE_CANDIDATO = "CANDIDATO"
STATE_CANDIDATO_FORTE = "CANDIDATO_FORTE"
STATES_ORDER = [
    STATE_DESCARTAR, STATE_OBSERVAR, STATE_CANDIDATO_FRACO,
    STATE_CANDIDATO, STATE_CANDIDATO_FORTE,
]
FORBIDDEN_TERMS = [
    "aposta garantida", "aposta certa", "garantia", "lucro garantido",
    "aposta segura",
]

# ---------------------------------------------------------------------------
# item 4: ranking dos rotulos de edge ja calculados na Fase 9
# (`src.odds.config.EDGE_STATUS_LABELS`), do mais fraco ao mais forte.
# Usado so para comparar "quanto edge foi atingido" -- edge maior NAO
# significa automaticamente melhor oportunidade (a qualidade da amostra e a
# staleness continuam entrando na decisao final, ver `rules.py`).
# ---------------------------------------------------------------------------
EDGE_RANK = {
    "ABAIXO_DO_LIMITE": 0,
    "ATINGE_EDGE_2": 1,
    "ATINGE_EDGE_3": 2,
    "ATINGE_EDGE_5": 3,
    "ATINGE_EDGE_7_5": 4,
    "ATINGE_EDGE_10": 5,
}
EDGE_RANK_LABELS = {v: k for k, v in EDGE_RANK.items()}
STRONG_EDGE_MIN_RANK = EDGE_RANK["ATINGE_EDGE_7_5"]

# ---------------------------------------------------------------------------
# item 5: qualidade de amostra -- thresholds fixados A PRIORI (antes de olhar
# qualquer resultado desta execucao), com base em 4 sinais:
#   - numero de partidas anteriores do jogador (`prior_matches_career`,
#     Fase 3/6/8 -- ja usado para `sample_bucket_career`);
#   - service points acumulados (`prior_service_points_career`, Fase 3);
#   - return points acumulados (`prior_return_points_career`, Fase 3);
#   - historico na MESMA superficie (`surface_prior_matches`, Fase 3);
# mais uma checagem de consistencia (nenhuma flag de baixa confianca ja
# herdada das Fases 7/8: cold_start / insufficient_history /
# calibrator_insufficient_sample). Dado ausente nunca e tratado como "OK" --
# cai para LOW (cautela maxima, nunca inventar dado -- CLAUDE.md #23).
# ---------------------------------------------------------------------------
SAMPLE_QUALITY_LOW = "LOW"
SAMPLE_QUALITY_MEDIUM = "MEDIUM"
SAMPLE_QUALITY_HIGH = "HIGH"

SAMPLE_QUALITY_THRESHOLDS = {
    "high_min_matches": 50,
    "high_min_service_points": 300,
    "high_min_return_points": 300,
    "high_min_surface_matches": 10,
    "medium_min_matches": 10,
    "medium_min_service_points": 60,
    "medium_min_return_points": 60,
}

# ---------------------------------------------------------------------------
# item 6: politica de staleness -- 3 faixas objetivas, fixadas antes de olhar
# os resultados desta execucao. A base historica atual tem corte em
# 2026-05-25 (docs/013/014), o que produz ~120 dias de defasagem em qualquer
# execucao feita em setembro/2026 -- os limiares abaixo foram escolhidos por
# criterio proprio (nao ajustados para "encaixar" o caso real), e o efeito
# de o caso real cair em MUITO_DEFASADO e reportado como achado (docs/016),
# nao escondido.
# ---------------------------------------------------------------------------
STALENESS_ATUAL_MAX_DAYS = 30
STALENESS_MODERADO_MAX_DAYS = 90
STALENESS_ATUAL = "ATUAL"
STALENESS_MODERADO = "MODERADAMENTE_DEFASADO"
STALENESS_MUITO_DEFASADO = "MUITO_DEFASADO"

# item 6: CANDIDATO_FORTE nunca e permitido quando a defasagem ultrapassa
# este limite (mesmo limite que separa MODERADO de MUITO_DEFASADO).
MAX_STALENESS_DAYS_FOR_CANDIDATO_FORTE = STALENESS_MODERADO_MAX_DAYS

# ---------------------------------------------------------------------------
# item 2: "odd observada superar o limite minimo configurado" -- um piso de
# liquidez/sanidade sobre a PROPRIA odd (distinto da odd minima por edge, ja
# calculada na Fase 7/9): odds muito proximas de 1.0 tem pouco valor
# operacional mesmo com edge tecnicamente positivo, porque um erro pequeno
# de calibracao do modelo já e suficiente para inverter o sinal. Fixado a
# priori, nao ajustado nos dados desta execucao.
# ---------------------------------------------------------------------------
MIN_LIQUID_ODDS = 1.30

# ---------------------------------------------------------------------------
# item 9: regras por mercado -- piso MINIMO de edge (entre os 5 ja definidos
# na Fase 7) abaixo do qual a oportunidade nunca passa de OBSERVAR, POR
# MERCADO. Isto e um valor TESTADO nesta fase (ver `build.py`, comparacao de
# sensibilidade contra um piso uniforme), nao a escolha definitiva de edge
# operacional (que a instrucao explicitamente NAO pede para fixar ainda).
# Motivo de cada piso, registrado a priori:
#   - aces_player: 3% -- ATP/Grass e restrito (gate separado); nos demais
#     segmentos a Fase 6.1 nao encontrou ganho extra de calibracao, entao um
#     piso intermediario evita reagir a ruido pequeno de odd.
#   - total_aces_match: 2% -- todos os 6 tour/mercado estao "PRONTO PARA
#     ODDS" (docs/012 secao 4) sem nenhuma ressalva de calibracao -- piso
#     mais baixo (o mesmo minimo ja testado na Fase 7).
#   - double_faults_player: 5% -- nunca teve variante Serve x Return
#     modelada (docs/012 secao 7), so a taxa bruta por oportunidade -- piso
#     mais alto por cautela adicional de modelagem mais simples.
# ---------------------------------------------------------------------------
# valores no mesmo namespace de `EDGE_RANK` acima (rotulos de status ja
# produzidos pela Fase 9 -- `src.odds.config.EDGE_STATUS_LABELS`), nunca o
# rotulo "Npct" bruto usado so internamente pela Fase 7 para os cenarios de
# odd minima.
MARKET_MIN_EDGE_LABEL = {
    "aces_player": "ATINGE_EDGE_3",
    "total_aces_match": "ATINGE_EDGE_2",
    "double_faults_player": "ATINGE_EDGE_5",
}
# cenario alternativo usado so para o teste de sensibilidade do item 9 (nunca
# usado como politica operacional) -- piso uniforme, o mais alto dos tres.
SENSITIVITY_UNIFORM_EDGE_LABEL = "ATINGE_EDGE_5"

# item 8: probabilidades extremas (>=90%, mesmo limiar da Fase 7) nunca
# recebem tratamento POSITIVO automatico -- apenas uma flag informativa, que
# nunca move a classificacao para cima nem para baixo sozinha.
EXTREME_PROBABILITY_CAUTION_ONLY = True

# item 12: nenhum calculo de stake nesta fase -- campo futuro fixo.
STAKE_POLICY_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

RANDOM_SEED = 20260922
