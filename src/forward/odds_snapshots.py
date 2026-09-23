"""Snapshots de odds pre-jogo (item 5) -- multiplas leituras da MESMA
oportunidade ao longo do tempo, sempre append-only (nunca sobrescreve uma
leitura anterior, mesma disciplina de `src.odds.storage`). Cada linha usa
`prediction_id` (`ids.make_prediction_id`) para se relacionar com
`forward_predictions.parquet` -- a previsao (probabilidade) e imutavel
(`predictions.py`); so a odd observada pode ter multiplas leituras aqui."""

from __future__ import annotations

import pandas as pd

from . import config as cfg
from . import ids

_SNAPSHOT_COLUMNS = ["snapshot_id", "prediction_id", "bookmaker", "decimal_odds", "collected_at"]
_DEDUP_KEY = ["prediction_id", "bookmaker", "collected_at", "decimal_odds"]


def record_snapshot(prediction_id: str, bookmaker: str, decimal_odds: float, collected_at: str | None = None) -> pd.DataFrame:
    collected_at = collected_at or pd.Timestamp.now("UTC").isoformat()
    row = pd.DataFrame([{
        "snapshot_id": ids.make_snapshot_id(prediction_id, collected_at),
        "prediction_id": prediction_id,
        "bookmaker": bookmaker,
        "decimal_odds": float(decimal_odds),
        "collected_at": collected_at,
    }])
    return append_snapshots(row)


def append_snapshots(new_rows: pd.DataFrame) -> pd.DataFrame:
    if new_rows.empty:
        return load_snapshots()

    if cfg.ODDS_SNAPSHOTS_PATH.exists():
        existing = pd.read_parquet(cfg.ODDS_SNAPSHOTS_PATH)
        combined = pd.concat([existing, new_rows[_SNAPSHOT_COLUMNS]], ignore_index=True)
    else:
        combined = new_rows[_SNAPSHOT_COLUMNS].reset_index(drop=True)

    combined = combined.drop_duplicates(subset=_DEDUP_KEY, keep="first").reset_index(drop=True)
    cfg.PHASE11_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(cfg.ODDS_SNAPSHOTS_PATH, index=False)
    return combined


def load_snapshots() -> pd.DataFrame:
    return pd.read_parquet(cfg.ODDS_SNAPSHOTS_PATH) if cfg.ODDS_SNAPSHOTS_PATH.exists() else pd.DataFrame(columns=_SNAPSHOT_COLUMNS)


def summarize_odds_movement(match_started_at: str | None = None) -> pd.DataFrame:
    """item 5/6: `first_observed_odds`, `last_observed_odds`,
    `best_observed_odds` (a MAIOR odd observada -- melhor preco em odd
    decimal, NUNCA assumido como executavel, so informativo, item 5) e
    `closing_odds_observed` (item 6: ultima observacao manual ANTES do
    inicio da partida quando `match_started_at` e informado; caso
    contrario, a ultima observacao disponivel de qualquer horario -- com a
    mesma ressalva textual do item 6 de que isso NAO e o fechamento oficial
    da casa)."""

    snaps = load_snapshots()
    if snaps.empty:
        return snaps

    snaps = snaps.copy()
    snaps["collected_at"] = pd.to_datetime(snaps["collected_at"], format="mixed", utc=True)

    if match_started_at is not None:
        cutoff = pd.Timestamp(match_started_at)
        if cutoff.tzinfo is None:
            cutoff = cutoff.tz_localize("UTC")
        pre_match = snaps[snaps["collected_at"] <= cutoff]
        closing_note = (
            "ultima observacao manual disponivel antes do inicio informado da "
            "partida -- nao necessariamente o fechamento oficial da casa (item 6)"
        )
    else:
        pre_match = snaps
        closing_note = (
            "nenhum horario de inicio de partida informado -- ultima observacao "
            "manual de qualquer horario, nao necessariamente o fechamento (item 6)"
        )

    rows = []
    for pid, g in snaps.groupby("prediction_id"):
        g = g.sort_values("collected_at")
        gp = pre_match[pre_match["prediction_id"] == pid].sort_values("collected_at")
        rows.append({
            "prediction_id": pid,
            "n_snapshots": int(len(g)),
            "first_observed_odds": float(g.iloc[0]["decimal_odds"]),
            "last_observed_odds": float(g.iloc[-1]["decimal_odds"]),
            "best_observed_odds": float(g["decimal_odds"].max()),
            "closing_odds_observed": float(gp.iloc[-1]["decimal_odds"]) if not gp.empty else float("nan"),
            "closing_odds_note": closing_note,
        })
    return pd.DataFrame(rows)
