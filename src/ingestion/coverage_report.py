"""Relatorio de cobertura de MatchStats (saque/devolucao) por ano/tour.

Nao normaliza nem transforma dados; apenas mede, por arquivo, a fracao de
partidas com estatisticas de saque ausentes (coluna w_ace/l_ace vazia), o
que e uma sinalizacao de qualidade/cobertura exigida na Fase 1.
"""

import csv
from pathlib import Path

from .config import SOURCES

STAT_COLUMNS = [
    "w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon", "w_SvGms", "w_bpSaved", "w_bpFaced",
    "l_ace", "l_df", "l_svpt", "l_1stIn", "l_1stWon", "l_2ndWon", "l_SvGms", "l_bpSaved", "l_bpFaced",
]


def coverage_for_file(path: Path) -> dict:
    if not path.exists():
        return {"exists": False}

    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        n_rows = 0
        n_missing_stats = 0
        for row in reader:
            n_rows += 1
            if any((row.get(col) or "").strip() == "" for col in STAT_COLUMNS):
                n_missing_stats += 1

    pct_missing = (n_missing_stats / n_rows * 100) if n_rows else None
    return {
        "exists": True,
        "n_rows": n_rows,
        "n_missing_matchstats": n_missing_stats,
        "pct_missing_matchstats": round(pct_missing, 2) if pct_missing is not None else None,
    }


def build_report() -> list:
    report = []
    for tour_key, source in SOURCES.items():
        for file_name in source["files"].get("matches", []):
            path = source["local_dir"] / file_name
            cov = coverage_for_file(path)
            cov.update({"tour": source["tour"], "file_name": file_name})
            report.append(cov)
    return report


if __name__ == "__main__":
    for row in build_report():
        print(row)
