"""CLI da Fase 7: odd justa e odd minima aceitavel por cenario de edge, a
partir da probabilidade operacional ja definida na Fase 6.1.

Le exclusivamente data/outputs/phase6/previsoes_por_linha.parquet e
data/outputs/phase6_1/previsoes_calibradas.parquet. Nao consulta casas de
apostas, nao faz scraping, nao calcula stake. Escreve em
data/outputs/phase7/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.pricing.build import run

if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
