"""CLI da Fase 10 (item 14): classifica cada odd comparada na Fase 9
(`data/outputs/phase9/comparison_with_model.parquet`) em um dos 5 estados
operacionais (DESCARTAR/OBSERVAR/CANDIDATO_FRACO/CANDIDATO/CANDIDATO_FORTE),
com motivos, flags e metricas explicitos -- nunca so um status.

Uso:

    python scripts/evaluate_opportunities.py

Nao calcula stake, nao faz aposta, nao cria interface.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.decision import build  # noqa: E402


def main() -> int:
    result = build.run()

    evaluated = result.pop("evaluated")
    if not evaluated.empty:
        for exp in evaluated["explanation"]:
            print(exp)
            print("-" * 40)

    print(json.dumps({k: v for k, v in result.items() if k != "operational_rules"}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
