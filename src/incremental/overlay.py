"""Gerenciamento de armazenamento e mesclagem operacional do Overlay Tennis Abstract (LOTE J).

Preserva 100% intacta a base oficial Sackmann (`data/processed/{tour}/matches.parquet`).
O overlay vive isolado em `data/processed/incremental_overlays/tennis_abstract/` e
é mesclado apenas operacionalmente em memória via `get_effective_matches`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pandas as pd

from src.normalization.config import PROCESSED_DIRS
from . import config as cfg
from .overlay_merge import write_overlay_atomic


def get_overlay_path(tour: str) -> Path:
    return cfg.TA_OVERLAY_DIR / tour.lower() / "matches.parquet"


def save_overlay_matches(tour: str, df: pd.DataFrame, run_id: str | None = None) -> Path:
    """Salva partidas normalizadas no diretório isolado do overlay.

    NUNCA grava em `data/processed/{tour}/matches.parquet`.
    Delegado a `overlay_merge.write_overlay_atomic`: rejeita (ValueError,
    antes de qualquer escrita) DataFrame vazio, colunas diferentes de
    `OUTPUT_COLUMNS` (mesmas colunas, mesma ordem), chave (match_id,
    player_id) duplicada, partida sem exatamente 2 linhas e qualquer escrita
    que removeria linhas já existentes. Escrita atômica com backup em
    `versions/`. Para incorporar coletas novas use `overlay_merge.merge_and_save`.
    """
    return write_overlay_atomic(tour, df, run_id)["path"]


def load_overlay_matches(tour: str) -> pd.DataFrame:
    """Carrega partidas do overlay se existirem, senão retorna DataFrame vazio."""
    path = get_overlay_path(tour)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def log_audit_event(event: dict[str, Any]) -> None:
    """Registra evento no log de auditoria do overlay (JSON lines)."""
    cfg.TA_AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "tennis_abstract",
        **event,
    }
    with open(cfg.TA_AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def get_player_freshness(
    player_name: str,
    tour: str,
    overlay_df: pd.DataFrame | None = None,
    source_status: str = "OK",
    has_partial_issues: bool = False,
) -> dict[str, Any]:
    """LEGADO/DEPRECADO (T7): freshness por NOME e por aparição no overlay.

    Não é fonte de verdade operacional: um jogador que só aparece como
    adversário vira UPDATED, e a chave é o nome. Mantido sem alteração apenas
    porque `api/services/radar_service.py` ainda o chama (API fora do escopo do
    T7). A lógica correta, por player_id e resultado da coleta, está em
    `src.incremental.player_freshness.build_player_freshness`."""
    tour_clean = tour.upper()
    base_cutoff = cfg.TA_BASE_CUTOFF

    if source_status in ("429", "403", "TIMEOUT", "ERROR", "UNAVAILABLE"):
        return {
            "player_name": player_name,
            "tour": tour_clean,
            "base_cutoff": base_cutoff,
            "overlay_last_match": None,
            "effective_data_cutoff": base_cutoff,
            "freshness_status": "SOURCE_UNAVAILABLE",
        }

    df = overlay_df if overlay_df is not None else load_overlay_matches(tour_clean)

    player_matches = pd.DataFrame()
    if not df.empty and "player_name" in df.columns:
        player_matches = df[df["player_name"].str.lower() == player_name.lower()]

    if player_matches.empty:
        return {
            "player_name": player_name,
            "tour": tour_clean,
            "base_cutoff": base_cutoff,
            "overlay_last_match": None,
            "effective_data_cutoff": base_cutoff,
            "freshness_status": "BASE_ONLY",
        }

    last_dt_raw = player_matches["tournament_date"].max()
    last_dt_str = str(last_dt_raw)
    if len(last_dt_str) == 8 and last_dt_str.isdigit():
        overlay_last_match = f"{last_dt_str[:4]}-{last_dt_str[4:6]}-{last_dt_str[6:]}"
    else:
        overlay_last_match = str(pd.to_datetime(last_dt_raw).date())

    status = "PARTIAL" if has_partial_issues else "UPDATED"

    return {
        "player_name": player_name,
        "tour": tour_clean,
        "base_cutoff": base_cutoff,
        "overlay_last_match": overlay_last_match,
        "effective_data_cutoff": overlay_last_match,
        "freshness_status": status,
    }


def load_base_matches(tour: str) -> pd.DataFrame:
    """Lê a base oficial congelada Sackmann. Somente leitura."""
    path = PROCESSED_DIRS[tour.lower()] / "matches.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def get_effective_matches(
    tour: str,
    override_overlay_df: pd.DataFrame | None = None,
    enabled: bool | None = None,
) -> pd.DataFrame:
    """Produz uma visão combinada da base oficial Sackmann + Overlay Tennis Abstract.

    A combinação ocorre exclusivamente em memória:
    `official Sackmann + recent overlay - duplicates`.
    A base em disco permanece intocada.
    """
    tour_clean = tour.upper()
    is_enabled = enabled if enabled is not None else cfg.TA_OVERLAY_ENABLED

    base = load_base_matches(tour_clean)
    if not is_enabled:
        return base

    overlay = override_overlay_df if override_overlay_df is not None else load_overlay_matches(tour_clean)
    if overlay.empty:
        return base

    # Garantir que não existam duplicatas entre base e overlay
    # Chave estável de deduplicação por linha: match_id + player_id
    existing_keys = set(base["match_id"].astype(str) + ":" + base["player_id"].astype(str))
    overlay_keys = overlay["match_id"].astype(str) + ":" + overlay["player_id"].astype(str)
    new_overlay = overlay[~overlay_keys.isin(existing_keys)]

    if new_overlay.empty:
        return base

    new_overlay = new_overlay.copy()
    if "tournament_date" in new_overlay.columns:
        new_overlay["tournament_date"] = pd.to_datetime(new_overlay["tournament_date"])

    combined = pd.concat([base, new_overlay], ignore_index=True)
    combined = combined.sort_values(
        ["tournament_date", "tourney_id", "match_id", "result"],
        ascending=[True, True, True, False],
    ).reset_index(drop=True)

    return combined
