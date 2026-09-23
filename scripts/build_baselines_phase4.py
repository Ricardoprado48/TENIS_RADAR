"""CLI da Fase 4 - baselines estatisticos e avaliacao walk-forward.

Uso: python scripts/build_baselines_phase4.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.baselines.build import run  # noqa: E402


def main():
    result = run()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
