"""Validacao basica de integridade dos CSVs baixados (sem pandas)."""

import csv
from collections import Counter
from pathlib import Path


def inspect_csv(path: Path) -> dict:
    """Le um CSV e retorna contagem de linhas/colunas e os nomes das colunas.

    Nao interpreta nem transforma os dados (Fase 1 = ingestao bruta).
    """
    if not path.exists():
        return {"exists": False}

    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            return {"exists": True, "n_rows": 0, "n_cols": 0, "columns": [], "empty_file": True}

        n_rows = 0
        ragged_rows = 0
        for row in reader:
            n_rows += 1
            if len(row) != len(header):
                ragged_rows += 1

    return {
        "exists": True,
        "empty_file": False,
        "n_rows": n_rows,
        "n_cols": len(header),
        "columns": header,
        "ragged_rows": ragged_rows,
    }


def reference_schema(schemas: list) -> list:
    """Escolhe o schema mais comum (por tupla de colunas) entre uma lista de listas de colunas."""
    counts = Counter(tuple(cols) for cols in schemas if cols)
    if not counts:
        return []
    return list(counts.most_common(1)[0][0])


def diff_columns(reference: list, candidate: list) -> dict:
    ref_set, cand_set = set(reference), set(candidate)
    return {
        "matches_reference": list(candidate) == list(reference),
        "missing_columns": sorted(ref_set - cand_set),
        "extra_columns": sorted(cand_set - ref_set),
        "order_differs": (ref_set == cand_set) and (list(candidate) != list(reference)),
    }
