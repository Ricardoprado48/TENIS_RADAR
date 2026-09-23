"""Configuracao da Fase 2 - normalizacao dos dados brutos Sackmann (ATP/WTA).

Le exclusivamente de data/raw/ (gerado na Fase 1). Nao faz downloads. Escreve
somente em data/processed/, nunca em data/raw/.
"""

from pathlib import Path

from src.ingestion.config import SOURCES  # reaproveita a lista de fontes/arquivos da Fase 1

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"

TOURS = ("atp", "wta")

RAW_DIRS = {tour: SOURCES[tour]["local_dir"] for tour in TOURS}
MATCH_FILES = {tour: SOURCES[tour]["files"]["matches"] for tour in TOURS}
PLAYERS_FILES = {tour: SOURCES[tour]["files"]["players"] for tour in TOURS}
RANKINGS_FILES = {tour: SOURCES[tour]["files"]["rankings"] for tour in TOURS}

PROCESSED_DIRS = {tour: DATA_PROCESSED / tour for tour in TOURS}

REPORTS_DIR = DATA_PROCESSED / "reports"
SAMPLES_DIR = DATA_PROCESSED / "samples"
