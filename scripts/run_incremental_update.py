"""CLI da Fase 8.1: atualizacao incremental da base historica + re-execucao
do radar da Fase 8 para comparacao.

Uso:
    python scripts/run_incremental_update.py

Nao consulta casas de apostas, nao coleta odds, nao calcula stake."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.incremental.build import run

if __name__ == "__main__":
    summary = run()
    print(json.dumps(summary, indent=2, default=str))
