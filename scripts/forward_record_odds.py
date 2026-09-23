"""CLI da Fase 11 (item 5): registra um novo snapshot de odds para uma
previsao ja registrada (`prediction_id`, ver forward_predictions.parquet).
Uma mesma oportunidade pode ter varios snapshots ao longo do dia -- nenhum
sobrescreve o anterior.

Uso:

    python scripts/forward_record_odds.py --prediction-id PRED_xxxx \\
        --bookmaker Betano --decimal-odds 1.80

Nao calcula stake, nao faz aposta, nao cria interface.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.forward import build  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prediction-id", required=True)
    parser.add_argument("--bookmaker", default="Betano")
    parser.add_argument("--decimal-odds", type=float, required=True)
    parser.add_argument("--collected-at", default=None)
    args = parser.parse_args()

    result = build.record_odds_for_prediction(args.prediction_id, args.bookmaker, args.decimal_odds, args.collected_at)
    print(f"{len(result)} snapshot(s) no total registrados para esta previsao.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
