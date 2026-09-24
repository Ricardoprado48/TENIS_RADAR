"""Materializa um snapshot Live Tennis no contrato bruto da Fase 8.

Entrada:
    data/raw/live_tennis/live_tennis_YYYYMMDDTHHMMSSZ.json

Saída:
    data/raw/phase8/partidas_futuras_YYYYMMDD.csv

A data do nome do CSV é a data UTC da coleta, seguindo o uso histórico da
Fase 8: o arquivo representa a fotografia operacional daquele dia e pode
conter partidas de datas futuras diferentes.

O arquivo bruto Live Tennis continua imutável. O CSV da Fase 8 é um artefato
derivado e reproduzível a partir daquele snapshot.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from . import config as cfg
from .live_tennis_normalizer import normalize_upcoming_to_phase8


class LiveTennisPhase8MaterializationError(ValueError):
    """Snapshot inválido ou insuficiente para gerar o contrato da Fase 8."""


def _parse_collected_at(raw: Any) -> datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise LiveTennisPhase8MaterializationError("snapshot sem collected_at")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LiveTennisPhase8MaterializationError(
            f"collected_at inválido: {raw!r}"
        ) from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise LiveTennisPhase8MaterializationError("collected_at sem timezone")
    return value


def load_live_tennis_snapshot(path: str | Path) -> dict[str, Any]:
    snapshot_path = Path(path)
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveTennisPhase8MaterializationError(
            f"snapshot inválido: {snapshot_path}"
        ) from exc

    if not isinstance(payload, dict):
        raise LiveTennisPhase8MaterializationError("snapshot fora do contrato esperado")
    if payload.get("schema_version") != 1:
        raise LiveTennisPhase8MaterializationError(
            f"schema_version não suportado: {payload.get('schema_version')!r}"
        )
    if not isinstance(payload.get("tours"), dict):
        raise LiveTennisPhase8MaterializationError("snapshot sem objeto tours")
    return payload


def snapshot_to_phase8_dataframe(path: str | Path) -> pd.DataFrame:
    payload = load_live_tennis_snapshot(path)
    collected_at = _parse_collected_at(payload.get("collected_at"))

    parts: list[pd.DataFrame] = []
    for tour in ("ATP", "WTA"):
        tour_payload = payload["tours"].get(tour)
        if not isinstance(tour_payload, dict):
            raise LiveTennisPhase8MaterializationError(
                f"snapshot sem bloco do tour {tour}"
            )

        upcoming = tour_payload.get("upcoming")
        fixtures = tour_payload.get("fixtures")
        if not isinstance(upcoming, list) or not isinstance(fixtures, list):
            raise LiveTennisPhase8MaterializationError(
                f"snapshot {tour} sem upcoming/fixtures válidos"
            )

        part = normalize_upcoming_to_phase8(
            tour,
            upcoming,
            fixtures,
            collected_at=collected_at,
        )
        parts.append(part)

    if not parts:
        return pd.DataFrame()

    out = pd.concat(parts, ignore_index=True)
    if not out.empty:
        out = out.sort_values(
            ["match_date", "scheduled_time_utc", "tour", "tournament", "live_tennis_match_id"],
            kind="stable",
        ).reset_index(drop=True)
    return out


def materialize_phase8_csv(
    snapshot_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> Path:
    payload = load_live_tennis_snapshot(snapshot_path)
    collected_at = _parse_collected_at(payload.get("collected_at"))
    df = snapshot_to_phase8_dataframe(snapshot_path)

    raw_dir = Path(output_dir) if output_dir is not None else cfg.PHASE8_RAW_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_path = raw_dir / f"partidas_futuras_{collected_at:%Y%m%d}.csv"

    # O arquivo diário é derivado do snapshot mais recente escolhido
    # explicitamente pelo operador. Gravação atômica evita arquivo parcial.
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    df.to_csv(tmp_path, index=False, encoding="utf-8")
    tmp_path.replace(output_path)

    # Validação pelo próprio contrato já usado pela Fase 8.
    from .sources import load_raw_matches

    loaded = load_raw_matches(output_path)
    if len(loaded) != len(df):
        raise LiveTennisPhase8MaterializationError(
            "quantidade de linhas mudou ao validar o CSV materializado"
        )

    return output_path
