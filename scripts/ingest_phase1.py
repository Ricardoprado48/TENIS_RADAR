"""CLI da Fase 1 — ingestao de dados historicos Sackmann (ATP/WTA, 2022-2026).

Uso:
    python scripts/ingest_phase1.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingestion.run import run  # noqa: E402


def main() -> None:
    result = run()
    print(f"Arquivos processados: {len(result['records'])}")
    print(f"Problemas detectados: {len(result['issues'])}")
    print(f"Commit da fonte (mirror): {result['repo_commit_sha']}")
    print(f"Manifesto JSON: {result['manifest_json']}")
    print(f"Manifesto Markdown: {result['manifest_md']}")
    if result["issues"]:
        print("\nProblemas:")
        for issue in result["issues"]:
            print(f"  - [{issue['type']}] {issue['file_name']}: {issue.get('detail', '')}")


if __name__ == "__main__":
    main()
