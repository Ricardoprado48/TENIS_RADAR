"""Gera o CSV bruto da Fase 8 a partir de um snapshot Live Tennis.

Uso:
    python scripts/materialize_live_tennis_phase8.py <snapshot.json>

Se nenhum caminho for informado, usa o snapshot Live Tennis mais recente.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.radar.live_tennis_phase8 import materialize_phase8_csv

LIVE_TENNIS_RAW_DIR = PROJECT_ROOT / "data" / "raw" / "live_tennis"


def _latest_snapshot() -> Path:
    files = sorted(LIVE_TENNIS_RAW_DIR.glob("live_tennis_*.json"))
    if not files:
        raise FileNotFoundError(
            f"nenhum snapshot Live Tennis encontrado em {LIVE_TENNIS_RAW_DIR}"
        )
    return files[-1]


def main() -> int:
    snapshot = Path(sys.argv[1]) if len(sys.argv) > 1 else _latest_snapshot()
    output = materialize_phase8_csv(snapshot)
    print(f"Phase 8 CSV salvo: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
