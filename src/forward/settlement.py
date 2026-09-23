"""Determinacao objetiva de settlement por oportunidade (item 8):
WIN/LOSS/VOID/UNRESOLVED/BOOKMAKER_RULE_REQUIRED.

`settlements.parquet` e um LOG append-only de EVENTOS de settlement (nao um
snapshot do estado atual) -- uma nova linha so e gravada quando o settlement
de um `prediction_id` muda em relacao a ultima linha ja gravada para ele
(mesma disciplina de dedup de `src.odds.storage`, aplicada aqui a transicao
UNRESOLVED -> estado final, em vez de a uma nova leitura de odd). Uma vez
que um `prediction_id` atinge um estado TERMINAL (WIN/LOSS/VOID), uma
tentativa de gravar um settlement TERMINAL diferente para o mesmo
`prediction_id` e rejeitada (item 1: nao recalcular retroativamente).

Retirement e walkover NUNCA recebem uma regra de settlement inventada
(item 8): o resultado esportivo bruto ja foi preservado por `results.py`, e
o settlement fica marcado `BOOKMAKER_RULE_REQUIRED` ate existir uma regra
documentada para a casa especifica (nenhuma foi documentada nesta fase --
ver docs/017)."""

from __future__ import annotations

import pandas as pd

from src.radar.identity import normalize_name

from . import config as cfg
from . import ids

_TERMINAL_STATES = {cfg.SETTLEMENT_WIN, cfg.SETTLEMENT_LOSS, cfg.SETTLEMENT_VOID}
_SETTLEMENT_COLUMNS = ["prediction_id", "match_key", "settlement", "settlement_reason", "settled_at"]


def _actual_stat(prediction: dict, result: dict):
    market = prediction.get("market")
    if market == "total_aces_match":
        return result.get("total_aces_match")

    player_norm = normalize_name(prediction.get("player") or "")
    a_norm = normalize_name(result.get("player_a") or "")
    b_norm = normalize_name(result.get("player_b") or "")

    if market == "aces_player":
        if player_norm == a_norm:
            return result.get("aces_player_a")
        if player_norm == b_norm:
            return result.get("aces_player_b")
        return None
    if market == "double_faults_player":
        if player_norm == a_norm:
            return result.get("double_faults_player_a")
        if player_norm == b_norm:
            return result.get("double_faults_player_b")
        return None
    return None


def _side_outcome(actual: float, line: float, side: str) -> str:
    if actual == line:
        return cfg.SETTLEMENT_VOID
    over_wins = actual > line
    if side == "over":
        return cfg.SETTLEMENT_WIN if over_wins else cfg.SETTLEMENT_LOSS
    return cfg.SETTLEMENT_LOSS if over_wins else cfg.SETTLEMENT_WIN


def settle_prediction(prediction: dict, result: dict | None) -> dict:
    pid = prediction["prediction_id"]

    if result is None:
        return {"prediction_id": pid, "settlement": cfg.SETTLEMENT_UNRESOLVED,
                "settlement_reason": "resultado da partida ainda nao registrado"}

    status = result.get("match_status")
    if status in (cfg.MATCH_STATUS_RETIREMENT, cfg.MATCH_STATUS_WALKOVER):
        return {
            "prediction_id": pid, "settlement": cfg.SETTLEMENT_BOOKMAKER_RULE_REQUIRED,
            "settlement_reason": (
                f"match_status={status} -- settlement depende de regra especifica da "
                "bookmaker, ainda nao documentada (item 8)"
            ),
        }
    if status != cfg.MATCH_STATUS_COMPLETED:
        return {"prediction_id": pid, "settlement": cfg.SETTLEMENT_UNRESOLVED,
                "settlement_reason": f"match_status invalido/inesperado: {status!r}"}

    actual = _actual_stat(prediction, result)
    if actual is None or actual != actual:
        return {"prediction_id": pid, "settlement": cfg.SETTLEMENT_UNRESOLVED,
                "settlement_reason": "estatistica real nao encontrada/nao casada com o jogador da previsao"}

    outcome = _side_outcome(float(actual), float(prediction["line"]), prediction["side"])
    return {
        "prediction_id": pid, "settlement": outcome,
        "settlement_reason": f"resultado real = {actual}, linha = {prediction['line']}, lado = {prediction['side']}",
    }


def _latest_by_prediction(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    latest = df.sort_values("settled_at").groupby("prediction_id", as_index=False).tail(1)
    return {r["prediction_id"]: r for r in latest.to_dict(orient="records")}


def settle_all(predictions: pd.DataFrame, results: pd.DataFrame, settled_at: str | None = None) -> dict:
    settled_at = settled_at or pd.Timestamp.now("UTC").isoformat()
    if predictions.empty:
        return {"new_events": pd.DataFrame(columns=_SETTLEMENT_COLUMNS), "rejected_overwrite_attempts": []}

    results_by_key = (
        {ids.make_match_key(r["tour"], r["match_id"]): r for r in results.to_dict(orient="records")}
        if not results.empty else {}
    )

    existing = pd.read_parquet(cfg.SETTLEMENTS_PATH) if cfg.SETTLEMENTS_PATH.exists() else pd.DataFrame(columns=_SETTLEMENT_COLUMNS)
    latest = _latest_by_prediction(existing)

    new_events, rejected = [], []
    for pred in predictions.to_dict(orient="records"):
        pid = pred["prediction_id"]
        match_key = ids.make_match_key(pred["tour"], pred["match_id"])
        result = results_by_key.get(match_key)
        outcome = settle_prediction(pred, result)

        prior = latest.get(pid)
        if prior is not None and prior.get("settlement") == outcome["settlement"]:
            continue  # nada mudou -- nao duplica o log

        if prior is not None and prior.get("settlement") in _TERMINAL_STATES:
            rejected.append({
                "prediction_id": pid,
                "reason": (
                    f"settlement ja finalizado como {prior.get('settlement')}, nova "
                    f"tentativa seria {outcome['settlement']} -- rejeitado (item 1, imutavel)"
                ),
            })
            continue

        outcome["settled_at"] = settled_at
        outcome["match_key"] = match_key
        new_events.append(outcome)
        latest[pid] = outcome

    if new_events:
        new_df = pd.DataFrame(new_events, columns=_SETTLEMENT_COLUMNS)
        combined = pd.concat([existing, new_df], ignore_index=True) if not existing.empty else new_df
        cfg.PHASE11_DIR.mkdir(parents=True, exist_ok=True)
        combined.to_parquet(cfg.SETTLEMENTS_PATH, index=False)

    return {
        "new_events": pd.DataFrame(new_events, columns=_SETTLEMENT_COLUMNS) if new_events else pd.DataFrame(columns=_SETTLEMENT_COLUMNS),
        "rejected_overwrite_attempts": rejected,
    }


def latest_settlements() -> pd.DataFrame:
    if not cfg.SETTLEMENTS_PATH.exists():
        return pd.DataFrame(columns=_SETTLEMENT_COLUMNS)
    existing = pd.read_parquet(cfg.SETTLEMENTS_PATH)
    if existing.empty:
        return existing
    return existing.sort_values("settled_at").groupby("prediction_id", as_index=False).tail(1)
