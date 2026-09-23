"""CLI da Fase 3: constroi as features historicas point-in-time (Serve x
Return) a partir de data/processed/{atp,wta}/matches.parquet (Fase 2) e
grava em data/processed/features/.

Uso:
    python scripts/build_features_phase3.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.features.build import run  # noqa: E402


def main():
    diagnostics = run()
    print("=" * 70)
    print("FASE 3 - FEATURES POINT-IN-TIME (Serve x Return)")
    print("=" * 70)
    for tour in ("atp", "wta"):
        d = diagnostics[tour]
        print(f"\n[{d['tour']}]")
        print(f"  linhas jogador-partida : {d['n_rows']}")
        print(f"  partidas               : {d['n_matches']}")
        print(f"  colunas                : {d['n_columns']}")
        print(f"  linhas cold start      : {d['n_cold_start_rows']} ({d['n_cold_start_rows']/d['n_rows']:.1%})")
        print(f"  score completo         : {d['score_complete_pct']:.1%}")
    print(f"\nParquet gravado em: data/processed/features/{{atp,wta}}/player_match_features.parquet")
    print(f"Relatorios em     : data/processed/features/reports/")
    print(f"Amostras em       : data/processed/features/samples/")


if __name__ == "__main__":
    main()
