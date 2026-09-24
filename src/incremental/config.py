"""Configuracao da Fase 8.1 - atualizacao incremental da base historica.

Le a base normalizada da Fase 2 (`data/processed/{tour}/matches.parquet`) e
a base bruta original da Fase 1 (`data/raw/sackmann_*`) SOMENTE PARA LEITURA
-- nenhum arquivo dessas duas fases e sobrescrito aqui (item 3 da instrucao).
"""

from __future__ import annotations

from pathlib import Path

from src.normalization.config import DATA_PROCESSED, DATA_RAW, PROCESSED_DIRS, RAW_DIRS, TOURS

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INCREMENTAL_RAW_DIR = DATA_RAW / "incremental_2026"
INCREMENTAL_OUTPUT_DIR = PROJECT_ROOT / "data" / "outputs" / "phase8_1"
INCREMENTAL_PROCESSED_DIR = DATA_PROCESSED / "incremental_2026"  # nunca escreve em data/processed/{tour}/

PHASE8_OUTPUT_DIR = PROJECT_ROOT / "data" / "outputs" / "phase8"

# Colunas do CSV bruto Sackmann exigidas por `src.normalization.matches.transform_raw_matches`.
# Uma fonte candidata so serve como atualizacao incremental compativel com o
# schema historico se puder preencher (sem inventar) todas estas colunas.
RAW_SCHEMA_COLUMNS = [
    "tourney_id", "tourney_name", "surface", "tourney_level", "tourney_date",
    "match_num", "round", "best_of", "minutes", "score",
    "winner_id", "winner_name", "winner_hand", "winner_rank", "winner_rank_points",
    "loser_id", "loser_name", "loser_hand", "loser_rank", "loser_rank_points",
    "w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon", "w_SvGms", "w_bpSaved", "w_bpFaced",
    "l_ace", "l_df", "l_svpt", "l_1stIn", "l_1stWon", "l_2ndWon", "l_SvGms", "l_bpSaved", "l_bpFaced",
]

# item 2 da instrucao: "dados minimos necessarios" -- subconjunto de
# RAW_SCHEMA_COLUMNS que carrega estatisticas de saque/devolucao (sem elas,
# uma partida so serve para atualizar identidade/ranking, nunca as features
# Serve x Return que alimentam os modelos das Fases 3-7).
STAT_COLUMNS = [
    "w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon", "w_SvGms", "w_bpSaved", "w_bpFaced",
    "l_ace", "l_df", "l_svpt", "l_1stIn", "l_1stWon", "l_2ndWon", "l_SvGms", "l_bpSaved", "l_bpFaced",
]

# Colunas de um "dataset de resultado" minimo (torneio, data, jogadores,
# placar) que NAO incluem estatisticas de saque -- usadas para classificar
# fontes candidatas como "somente resultado" (score-only).
RESULT_ONLY_COLUMNS = ["tourney_name", "tourney_date", "round", "winner_name", "loser_name", "score"]

MANIFEST_JSON = INCREMENTAL_RAW_DIR / "incremental_manifest.json"
INVESTIGATION_JSON = INCREMENTAL_RAW_DIR / "source_investigation.json"
INVESTIGATION_MD = INCREMENTAL_RAW_DIR / "source_investigation.md"

SUMMARY_JSON = INCREMENTAL_OUTPUT_DIR / "phase8_1_summary.json"
COVERAGE_CSV = INCREMENTAL_OUTPUT_DIR / "cobertura_incremental.csv"
COMPARISON_CSV = INCREMENTAL_OUTPUT_DIR / "comparacao_radar_antes_depois.csv"

# ids sinteticos para jogadores novos encontrados em dados incrementais que
# nao existem em data/processed/{tour}/players.parquet -- nunca reaproveita
# silenciosamente o id de um jogador existente (ver src.incremental.identity_new).
NEW_PLAYER_ID_PREFIX = "NEW"

# ==============================================================================
# LOTE J — TENNIS ABSTRACT INCREMENTAL OVERLAY
# ==============================================================================
import os

TA_CACHE_DIR = DATA_RAW / "tennis_abstract_cache"
TA_OVERLAY_DIR = DATA_PROCESSED / "incremental_overlays" / "tennis_abstract"
TA_AUDIT_LOG_PATH = TA_OVERLAY_DIR / "update_audit_log.jsonl"

TA_BASE_CUTOFF = "2026-05-25"
TA_CACHE_TTL_HOURS = float(os.environ.get("TENNIS_RADAR_TA_CACHE_TTL_HOURS", "24.0"))
TA_REQUEST_DELAY_SECONDS = float(os.environ.get("TENNIS_RADAR_TA_REQUEST_DELAY_SECONDS", "2.5"))
TA_OVERLAY_ENABLED = os.environ.get("TENNIS_RADAR_TA_OVERLAY_ENABLED", "false").lower() in ("1", "true", "yes")

__all__ = [
    "TOURS", "DATA_RAW", "DATA_PROCESSED", "RAW_DIRS", "PROCESSED_DIRS",
    "INCREMENTAL_RAW_DIR", "INCREMENTAL_OUTPUT_DIR", "INCREMENTAL_PROCESSED_DIR",
    "PHASE8_OUTPUT_DIR", "RAW_SCHEMA_COLUMNS", "STAT_COLUMNS", "RESULT_ONLY_COLUMNS",
    "MANIFEST_JSON", "INVESTIGATION_JSON", "INVESTIGATION_MD",
    "SUMMARY_JSON", "COVERAGE_CSV", "COMPARISON_CSV", "NEW_PLAYER_ID_PREFIX",
    "TA_CACHE_DIR", "TA_OVERLAY_DIR", "TA_AUDIT_LOG_PATH", "TA_BASE_CUTOFF",
    "TA_CACHE_TTL_HOURS", "TA_REQUEST_DELAY_SECONDS", "TA_OVERLAY_ENABLED",
]

