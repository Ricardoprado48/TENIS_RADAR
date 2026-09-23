"""CLI da Fase 11 (itens 18, 19): imprime o relatorio diario e o dashboard
cumulativo de acompanhamento.

Uso:

    python scripts/forward_report.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.forward import build  # noqa: E402


def main() -> int:
    print(build.daily_report())
    print()
    print("=" * 40)
    print()
    print(build.cumulative_dashboard())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
