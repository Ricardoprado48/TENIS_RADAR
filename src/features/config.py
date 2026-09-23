"""Configuracao da Fase 3 - features historicas point-in-time (Serve x Return).

Le exclusivamente de data/processed/ (gerado na Fase 2). Nao recalcula nem
sobrescreve os parquets normalizados da Fase 2. Escreve somente em
data/processed/features/.
"""

from pathlib import Path

from src.normalization.config import DATA_PROCESSED, PROCESSED_DIRS, TOURS  # noqa: F401

FEATURES_DIR = DATA_PROCESSED / "features"
FEATURES_TOUR_DIRS = {tour: FEATURES_DIR / tour for tour in TOURS}
FEATURES_REPORTS_DIR = FEATURES_DIR / "reports"
FEATURES_SAMPLES_DIR = FEATURES_DIR / "samples"

# janelas de historico exigidas na Fase 3 (item 4 da instrucao)
LAST_N_WINDOWS = {
    "last10": 10,
    "last20": 20,
    "last50": 50,
}
TIME_WINDOWS_DAYS = {
    "last365d": 365,
}
# "career" (toda a carreira anterior) e "surface_career" (carreira anterior na
# mesma superficie) sao tratados a parte por serem "all prior", sem limite de N.

# meia-vida padrao (dias) materializada na base de saida. A funcao de decay
# aceita qualquer meia-vida (parametrizavel); esta e apenas a versao gravada
# em disco para nao explodir o numero de colunas (ver docs/007, secao 5).
DEFAULT_DECAY_HALFLIFE_DAYS = 90

# janelas "headline" usadas nas features comparativas de matchup e no ajuste
# por adversario, para conter o numero de colunas (ver docs/007).
HEADLINE_WINDOWS = ["career", "surface_career", "last50"]
