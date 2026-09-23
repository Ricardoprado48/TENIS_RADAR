"""CLI da Fase 2: normaliza data/raw/ para data/processed/.

Uso: python scripts/normalize_phase2.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.normalization.run import run  # noqa: E402


def main() -> int:
    result = run()
    diag = result["diagnostics"]

    print("=== Fase 2 - normalizacao concluida ===")
    print(f"Total de linhas jogador-partida: {diag['n_total_player_match_rows']}")
    print(f"Total de partidas (match_id unicos): {diag['n_total_matches']}")

    for tour, d in diag["matches"].items():
        print(f"\n[{tour.upper()}] partidas brutas={d['n_raw_matches']} "
              f"usadas={d['n_matches_used']} linhas={d['n_player_match_rows']} "
              f"linhas_ok={d['rows_match_expected']} "
              f"ids_ausentes={d['n_matches_missing_player_id']} "
              f"match_id_duplicado={d['n_duplicate_match_ids']}")

    any_issue = False
    for tour, v in diag["validation"].items():
        two_rows = v["two_rows_per_match"]
        mirror = v["opponent_mirroring"]
        ids = v["ids"]
        if two_rows["n_matches_with_wrong_row_count"] or mirror["n_field_mismatches_total"] or \
           ids["n_missing_player_id"] or ids["n_missing_opponent_id"] or ids["n_missing_match_id"]:
            any_issue = True
            print(f"\n[ALERTA] problemas de validacao em {tour.upper()}:")
            print(json.dumps(v, indent=2, ensure_ascii=False))

    if not any_issue:
        print("\nValidacoes: sem problemas (2 linhas/partida, espelhamento correto, sem IDs ausentes).")

    print(f"\nRelatorios em: {Path('data/processed/reports').resolve()}")
    print(f"Amostras em:   {Path('data/processed/samples').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
