"""Snapshot imutável da agenda bruta obtida da Live Tennis API.

Este módulo preserva a evidência de coleta em data/raw/live_tennis/ sem
sobrescrever arquivos anteriores. O conteúdo salvo não inclui a chave da API.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .live_tennis import BASE_URL, LiveTennisClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIVE_TENNIS_RAW_DIR = PROJECT_ROOT / "data" / "raw" / "live_tennis"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp_token(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("collected_at deve possuir timezone")
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def collect_live_tennis_snapshot(
    client: LiveTennisClient,
    *,
    output_dir: str | Path | None = None,
    collected_at: datetime | None = None,
) -> Path:
    """Coleta ATP/WTA upcoming + fixtures e grava um JSON imutável.

    O arquivo usa modo exclusivo (`x`): uma coleta nunca substitui outra.
    """

    collected = collected_at or _utc_now()
    if collected.tzinfo is None or collected.utcoffset() is None:
        raise ValueError("collected_at deve possuir timezone")
    collected_utc = collected.astimezone(timezone.utc)

    tours: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for tour in ("ATP", "WTA"):
        tours[tour] = {
            "upcoming": client.list_upcoming_singles(tour),
            "fixtures": client.list_fixtures_singles(tour),
        }

    payload = {
        "schema_version": 1,
        "source": "Live Tennis API",
        "base_url": BASE_URL,
        "collected_at": collected_utc.isoformat().replace("+00:00", "Z"),
        "queries": {
            "upcoming": "/matches?status=upcoming&tour={tour}&draw=singles",
            "fixtures": "/fixtures?tour={tour}&draw=singles",
        },
        "tours": tours,
    }

    raw_dir = Path(output_dir) if output_dir is not None else LIVE_TENNIS_RAW_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"live_tennis_{_timestamp_token(collected_utc)}.json"

    with path.open("x", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

    return path
