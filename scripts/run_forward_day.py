"""CLI agregador da Fase 11 (item 17): registra as oportunidades novas do
dia, aplica settlement sobre o que ja tem resultado, e imprime os relatorios
(itens 18/19). Nao exige nenhuma casa de apostas automatica -- odds
continuam manuais (Fase 9).

Uso:

    python scripts/run_forward_day.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.forward import build  # noqa: E402


def main() -> int:
    result = build.run_forward_day()
    print(result["daily_report"])
    print()
    print("=" * 40)
    print()
    print(result["cumulative_dashboard"])
    print()
    rest = {k: v for k, v in result.items() if k not in ("daily_report", "cumulative_dashboard")}
    print(json.dumps(rest, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
