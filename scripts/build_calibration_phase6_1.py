"""CLI da Fase 6.1: calibracao das probabilidades out-of-sample da Fase 6
(Platt scaling / Isotonic regression, com calibracao temporal anti-leakage).

Le exclusivamente data/outputs/phase6/previsoes_por_linha.parquet. Nao
altera os modelos de contagem da Fase 6. Escreve em data/outputs/phase6_1/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.recalibration.build import run

if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
