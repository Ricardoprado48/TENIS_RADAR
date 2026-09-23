"""CLI da Fase 6: distribuicoes probabilisticas e calibracao dos mercados
selecionados (aces_player, total_aces_match, double_faults_player).

Le exclusivamente data/outputs/phase4/ (previsoes + parametros de dispersao
ja produzidos) e data/outputs/phase5/ (melhor abordagem por mercado). Nao
treina nenhum modelo novo. Escreve em data/outputs/phase6/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.probabilistic.build import run

if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
