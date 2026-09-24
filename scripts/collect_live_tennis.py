"""Coleta uma fotografia imutável da agenda Live Tennis.

Uso:
    python scripts/collect_live_tennis.py

Como os demais scripts Python do projeto, este arquivo adiciona explicitamente
a raiz do repositório ao sys.path antes de importar `src.*`. Isso permite
execução direta via `python scripts/<arquivo>.py`, padrão já usado em
`scripts/build_daily_radar.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.radar.live_tennis import LiveTennisClient
from src.radar.live_tennis_snapshot import collect_live_tennis_snapshot


def main() -> int:
    client = LiveTennisClient()
    path = collect_live_tennis_snapshot(client)
    print(f"Snapshot salvo: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
