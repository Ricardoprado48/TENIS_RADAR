"""CLI da Fase 11 (itens 8, 17): registra resultado real de partidas (via
--input-json) e aplica o settlement objetivo
(WIN/LOSS/VOID/UNRESOLVED/BOOKMAKER_RULE_REQUIRED) sobre todas as previsoes
ja registradas, recalculando metricas, paper test e CLV.

Uso:

    python scripts/forward_settle.py --input-json data/raw/phase11_manual/resultados.json
    python scripts/forward_settle.py   # so recalcula settlement/metricas com os resultados ja registrados

Nao calcula stake, nao faz aposta, nao cria interface.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.forward import build  # noqa: E402


def _entries_from_json(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else [data]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-json", dest="input_json", default=None)
    args = parser.parse_args()

    recorded = []
    if args.input_json:
        for entry in _entries_from_json(args.input_json):
            recorded.append(build.record_match_result(entry))

    settle_result = build.settle_day()
    print(json.dumps({"results_recorded": recorded, "settle": settle_result}, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
