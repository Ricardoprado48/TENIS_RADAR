"""CLI da Fase 8: radar diario de partidas futuras.

Uso:
    python scripts/build_daily_radar.py [caminho_para_csv_de_partidas_futuras]

Sem argumento, usa o arquivo bruto mais recente em data/raw/phase8/
(partidas_futuras_*.csv). Pipeline: obter partidas -> resolver jogadores ->
reconstruir features point-in-time -> gerar probabilidades (lambda + r) ->
calibrar -> odd justa/minima -> radar diario. Nao consulta casas de
apostas, nao faz scraping de odds, nao calcula stake, nao cria interface.
Escreve em data/outputs/phase8/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.radar.build import run

if __name__ == "__main__":
    raw_path = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps(run(raw_path), indent=2, default=str))
