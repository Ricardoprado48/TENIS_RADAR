"""Verificação de identidade da página Tennis Abstract (LOTE J, T4).

O `player_id` já vem de `agenda_players` e nunca é re-resolvido por nome. A
página TA coletada só é aceita como sendo desse jogador se as partidas dela
que DEVERIAM existir no Sackmann de fato existem lá com esse `player_id`:

    comparáveis = partidas TA com matchid válido, data dentro da janela da
                  base, level e round aceitos pela política da base
                  (qualifying e níveis ausentes da base ficam fora)
    overlap     = comparáveis cujo match_id está no Sackmann com o player_id

    NO_PLAYER_DATA         página sem dados utilizáveis (modelo/vazia)
    FETCH_FAILED           403/429/erro HTTP/rede: nada a verificar
    INSUFFICIENT_EVIDENCE  comparáveis < 3 (nunca chamado de mismatch)
    VERIFIED               comparáveis >= 3 e overlap >= 80%
    MISMATCH               comparáveis >= 3 e overlap < 80%

Só VERIFIED libera partidas para o overlay (gate no adapter).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.normalization.config import PROCESSED_DIRS

from . import tennis_abstract_source as tas
from .tennis_abstract_adapter import AcceptancePolicy, parse_matchid

VERIFIED = "VERIFIED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
MISMATCH = "MISMATCH"
NO_PLAYER_DATA = "NO_PLAYER_DATA"
FETCH_FAILED = "FETCH_FAILED"

MIN_COMPARABLE_MATCHES = 3
MIN_OVERLAP_RATIO = 0.80

_NO_DATA_FETCH = (tas.EMPTY_PAGE, tas.NO_PLAYER_DATA)
_FAILED_FETCH = (tas.HTTP_403, tas.HTTP_429, tas.HTTP_ERROR, tas.NETWORK_ERROR)


@dataclass(frozen=True)
class IdentityWindow:
    """Janela temporal (inclusiva) coberta pela base Sackmann do tour."""
    start: pd.Timestamp
    end: pd.Timestamp


def window_from_history(history: pd.DataFrame) -> IdentityWindow:
    dates = pd.to_datetime(history["tournament_date"])
    return IdentityWindow(dates.min(), dates.max())


def load_identity_history(tour: str) -> pd.DataFrame:
    """Somente leitura: match_id, player_id e tournament_date da base Sackmann."""
    return pd.read_parquet(
        PROCESSED_DIRS[tour.lower()] / "matches.parquet",
        columns=["match_id", "player_id", "tournament_date"],
    )


def comparable_match_ids(
    matches: list[dict[str, str]],
    tour: str,
    policy: AcceptancePolicy,
    window: IdentityWindow,
) -> tuple[set[str], dict[str, int]]:
    """match_ids TA que deveriam existir no Sackmann + contagem dos excluídos."""
    ids: set[str] = set()
    excluded: dict[str, int] = {}

    def _skip(reason: str) -> None:
        excluded[reason] = excluded.get(reason, 0) + 1

    for m in matches:
        parsed = parse_matchid(m.get("matchid") or "")
        if parsed is None:
            _skip("INVALID_MATCHID")
            continue
        date = pd.to_datetime((m.get("date") or "").strip(), format="%Y%m%d", errors="coerce")
        if pd.isna(date):
            _skip("INVALID_DATE")
            continue
        if not (window.start <= date <= window.end):
            _skip("OUTSIDE_BASE_WINDOW")
            continue
        level = (m.get("level") or "").strip()
        if level not in policy.levels:
            _skip("LEVEL_OUT_OF_POLICY")
            continue
        rnd = (m.get("round") or "").strip()
        if rnd not in policy.rounds:
            _skip("ROUND_OUT_OF_POLICY")
            continue
        ids.add(f"{tour.upper()}:{parsed[0]}:{parsed[1]}")
    return ids, excluded


def verify_identity(
    player_id: str,
    payload: dict[str, Any],
    history: pd.DataFrame,
    policy: AcceptancePolicy,
    window: IdentityWindow | None = None,
) -> dict[str, Any]:
    """Confirma que a página TA em `payload` é do `player_id` conhecido.

    `history`: base Sackmann do tour (match_id, player_id, tournament_date).
    Função pura: não lê nem grava arquivos."""
    p_info = payload.get("player", {}) or {}
    payload_pid = p_info.get("player_id")
    if payload_pid and payload_pid != player_id:
        raise ValueError(f"payload é de {payload_pid}, verificação pedida para {player_id}")
    tour = (p_info.get("tour") or player_id.split("-", 1)[0]).upper()
    matches = payload.get("matches") or []
    fetch_status = payload.get("fetch_status") or (tas.PAGE_OK if matches else tas.NO_PLAYER_DATA)
    window = window or window_from_history(history)

    out: dict[str, Any] = {
        "player_id": player_id,
        "tour": tour,
        "slug": p_info.get("slug"),
        "slug_source": p_info.get("slug_source"),
        "fetch_status": fetch_status,
        "page_fullname": payload.get("page_fullname"),
        "n_ta_matches": len(matches),
        "comparable_matches": 0,
        "overlap_matches": 0,
        "overlap_ratio": None,
        "identity_status": None,
        "reason": None,
        "excluded_from_denominator": {},
        "window_start": window.start.date().isoformat(),
        "window_end": window.end.date().isoformat(),
    }

    if fetch_status in _FAILED_FETCH:
        return {**out, "identity_status": FETCH_FAILED, "reason": f"coleta falhou: {fetch_status}"}
    if fetch_status in _NO_DATA_FETCH or not matches:
        return {**out, "identity_status": NO_PLAYER_DATA, "reason": f"página sem dados utilizáveis ({fetch_status})"}

    comparable, excluded = comparable_match_ids(matches, tour, policy, window)
    own_ids = set(history.loc[history["player_id"] == player_id, "match_id"].astype(str))
    n_comp = len(comparable)
    n_overlap = len(comparable & own_ids)
    ratio = n_overlap / n_comp if n_comp else None
    out.update(comparable_matches=n_comp, overlap_matches=n_overlap,
               overlap_ratio=ratio, excluded_from_denominator=excluded)

    if n_comp < MIN_COMPARABLE_MATCHES:
        status = INSUFFICIENT_EVIDENCE
        reason = f"{n_comp} partida(s) comparável(is) < mínimo {MIN_COMPARABLE_MATCHES}"
    elif ratio >= MIN_OVERLAP_RATIO:
        status = VERIFIED
        reason = f"overlap {n_overlap}/{n_comp} >= {MIN_OVERLAP_RATIO:.0%}"
    else:
        status = MISMATCH
        reason = f"overlap {n_overlap}/{n_comp} < {MIN_OVERLAP_RATIO:.0%}"
    return {**out, "identity_status": status, "reason": reason}


def attach_identity(payload: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    """Cópia rasa do payload com o resultado da verificação (lido pelo gate do adapter)."""
    return {**payload, "identity": verification}
