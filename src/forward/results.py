"""Registro do resultado real da partida (item 7) -- imutavel por
(`tour`, `match_id`), append-only. Preserva o resultado BRUTO (contagens
reais de aces/double faults, status da partida) -- a decisao objetiva de
WIN/LOSS/VOID/UNRESOLVED/BOOKMAKER_RULE_REQUIRED por oportunidade fica
inteiramente em `settlement.py`, nunca aqui."""

from __future__ import annotations

import pandas as pd

from . import config as cfg
from . import ids

_RESULT_COLUMNS = [
    "match_key", "tour", "match_id", "match_status",
    "player_a", "player_b", "aces_player_a", "aces_player_b",
    "double_faults_player_a", "double_faults_player_b", "total_aces_match",
    "sets_player_a", "sets_player_b", "recorded_at",
]

# item 7: "preservar o resultado bruto" -- uma tentativa de gravar um valor
# BRUTO diferente para uma partida ja registrada e uma tentativa de
# sobrescrita, rejeitada (mesma disciplina de imutabilidade do item 1).
_IMMUTABLE_CHECK_FIELDS = [
    "match_status", "aces_player_a", "aces_player_b",
    "double_faults_player_a", "double_faults_player_b",
]


def _values_equal(a, b) -> bool:
    try:
        if a is None and b is None:
            return True
        if isinstance(a, float) or isinstance(b, float):
            fa, fb = float(a), float(b)
            if fa != fa and fb != fb:
                return True
            return abs(fa - fb) < 1e-9
        return a == b
    except (TypeError, ValueError):
        return a == b


def load_results() -> pd.DataFrame:
    return pd.read_parquet(cfg.RESULTS_PATH) if cfg.RESULTS_PATH.exists() else pd.DataFrame(columns=_RESULT_COLUMNS)


def record_result(entry: dict, recorded_at: str | None = None) -> dict:
    tour = entry["tour"]
    match_id = entry["match_id"]
    status = entry.get("match_status")
    if status not in cfg.VALID_MATCH_STATUSES:
        raise ValueError(f"match_status invalido: {status!r} (esperado um de {cfg.VALID_MATCH_STATUSES})")

    match_key = ids.make_match_key(tour, match_id)
    recorded_at = recorded_at or pd.Timestamp.now("UTC").isoformat()

    aces_a = entry.get("aces_player_a")
    aces_b = entry.get("aces_player_b")
    total_aces = entry.get("total_aces_match")
    if total_aces is None and aces_a is not None and aces_b is not None:
        total_aces = aces_a + aces_b

    row = {
        "match_key": match_key, "tour": tour, "match_id": match_id,
        "match_status": status,
        "player_a": entry.get("player_a"), "player_b": entry.get("player_b"),
        "aces_player_a": aces_a, "aces_player_b": aces_b,
        "double_faults_player_a": entry.get("double_faults_player_a"),
        "double_faults_player_b": entry.get("double_faults_player_b"),
        "total_aces_match": total_aces,
        "sets_player_a": entry.get("sets_player_a"), "sets_player_b": entry.get("sets_player_b"),
        "recorded_at": recorded_at,
    }

    existing = load_results()
    prior = existing[existing["match_key"] == match_key] if not existing.empty else existing
    if not prior.empty:
        prior_row = prior.iloc[0].to_dict()
        changed = [f for f in _IMMUTABLE_CHECK_FIELDS if not _values_equal(prior_row.get(f), row.get(f))]
        if changed:
            return {"status": "rejected_overwrite_attempt", "changed_fields": changed, "row": row}
        return {"status": "already_recorded", "row": prior_row}

    combined = pd.concat([existing, pd.DataFrame([row])], ignore_index=True) if not existing.empty else pd.DataFrame([row])
    cfg.PHASE11_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(cfg.RESULTS_PATH, index=False)
    return {"status": "recorded", "row": row}
