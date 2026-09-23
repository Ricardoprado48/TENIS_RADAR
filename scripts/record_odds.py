"""CLI da Fase 9 (item 3): entrada manual de odds observadas em uma casa,
comparadas com o radar ja gerado pela Fase 8.

Uso — uma linha via flags:

    python scripts/record_odds.py \
        --bookmaker Betano --tour ATP --market aces_player \
        --player "Sebastian Baez" --line 7.5 \
        --over-odds 1.85 --under-odds 1.90 \
        --source-url "https://www.betano.bet.br/..."

Uso — lote via JSON ou CSV (cada linha/objeto com os mesmos campos):

    python scripts/record_odds.py --input-json data/raw/phase9_manual/hoje.json
    python scripts/record_odds.py --input-csv data/raw/phase9_manual/hoje.csv

Nao calcula stake, nao faz aposta, nao cria interface.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.odds import build  # noqa: E402


def _entry_from_args(args: argparse.Namespace) -> dict:
    return {
        "bookmaker": args.bookmaker,
        "tour": args.tour,
        "market": args.market,
        "player": args.player,
        "opponent": args.opponent,
        "tournament": args.tournament,
        "line": args.line,
        "over_odds": args.over_odds,
        "under_odds": args.under_odds,
        "collected_at": args.collected_at,
        "source_method": args.source_method,
        "source_url": args.source_url,
    }


def _entries_from_json(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else [data]


def _entries_from_csv(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bookmaker", default="Betano")
    parser.add_argument("--tour", choices=["ATP", "WTA"])
    parser.add_argument("--market", choices=["aces_player", "total_aces_match", "double_faults_player"])
    parser.add_argument("--player")
    parser.add_argument("--opponent", default=None)
    parser.add_argument("--tournament", default=None)
    parser.add_argument("--line", type=float)
    parser.add_argument("--over-odds", dest="over_odds", type=float, default=None)
    parser.add_argument("--under-odds", dest="under_odds", type=float, default=None)
    parser.add_argument("--collected-at", dest="collected_at", default=None)
    parser.add_argument("--source-method", dest="source_method", default="manual")
    parser.add_argument("--source-url", dest="source_url", default=None)
    parser.add_argument("--input-json", dest="input_json", default=None)
    parser.add_argument("--input-csv", dest="input_csv", default=None)
    parser.add_argument("--skip-betano-investigation", action="store_true")
    args = parser.parse_args()

    if args.input_json:
        entries = _entries_from_json(args.input_json)
    elif args.input_csv:
        entries = _entries_from_csv(args.input_csv)
    else:
        if not (args.tour and args.market and args.player and args.line is not None):
            parser.error("informe --tour --market --player --line (ou --input-json/--input-csv)")
        entries = [_entry_from_args(args)]

    result = build.run(entries=entries, investigate_betano=not args.skip_betano_investigation)

    for report in result["reports"]:
        print(report)
        print("-" * 40)

    if result["errors"]:
        print(f"{len(result['errors'])} entrada(s) rejeitada(s):", file=sys.stderr)
        for err in result["errors"]:
            print(f"  [{err['entry_index']}] {err['error']}", file=sys.stderr)

    print(json.dumps({k: v for k, v in result.items() if k not in ("reports", "errors")}, indent=2, ensure_ascii=False))
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
