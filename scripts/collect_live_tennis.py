"""Coleta uma fotografia imutável da agenda Live Tennis.

Uso:
    python scripts/collect_live_tennis.py
"""

from __future__ import annotations

from src.radar.live_tennis import LiveTennisClient
from src.radar.live_tennis_snapshot import collect_live_tennis_snapshot


def main() -> int:
    client = LiveTennisClient()
    path = collect_live_tennis_snapshot(client)
    print(f"Snapshot salvo: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
