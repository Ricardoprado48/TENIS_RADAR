"""Orquestrador da Fase 1: baixa, valida e registra os arquivos brutos ATP/WTA."""

from pathlib import Path

from . import github_source, manifest, validate
from .config import MANIFEST_JSON, MANIFEST_MD, MIRROR_BRANCH, MIRROR_REPO, SOURCES
from .download import fetch_and_store


def run() -> dict:
    repo_commit_sha = github_source.get_branch_head_commit(MIRROR_REPO, MIRROR_BRANCH)

    records = []
    issues = []
    schemas_by_category = {}  # (tour, category) -> list of column lists

    for tour_key, source in SOURCES.items():
        for category, file_list in source["files"].items():
            for file_name in file_list:
                remote_path = f"{source['mirror_dir']}/{file_name}"
                local_path = source["local_dir"] / file_name

                record = fetch_and_store(
                    repo=MIRROR_REPO,
                    branch=MIRROR_BRANCH,
                    remote_path=remote_path,
                    local_path=local_path,
                    repo_commit_sha=repo_commit_sha,
                    tour=source["tour"],
                    category=category,
                )

                if record["status"] == "missing":
                    issues.append({
                        "type": "missing_file",
                        "file_name": file_name,
                        "detail": record.get("error", ""),
                    })
                    records.append(record)
                    continue

                if record["status"] == "conflict_manual_review_required":
                    issues.append({
                        "type": "conflict",
                        "file_name": file_name,
                        "detail": "conteudo local difere do baixado; revisar manualmente "
                                  f"({record.get('conflict_file')})",
                    })

                # valida o arquivo que esta em disco (o original, nunca o .conflict-*)
                if local_path.exists():
                    inspection = validate.inspect_csv(local_path)
                    record.update({
                        "n_rows": inspection.get("n_rows"),
                        "n_cols": inspection.get("n_cols"),
                    })
                    if category in ("matches", "players", "rankings"):
                        columns = inspection.get("columns", [])
                        schemas_by_category.setdefault((source["tour"], category), []).append(
                            (file_name, columns)
                        )
                        if inspection.get("empty_file"):
                            issues.append({
                                "type": "empty_file",
                                "file_name": file_name,
                                "detail": "arquivo existe mas nao tem cabecalho/linhas",
                            })
                        elif inspection.get("n_rows", 0) == 0:
                            issues.append({
                                "type": "incomplete_file",
                                "file_name": file_name,
                                "detail": "cabecalho presente mas 0 linhas de dados",
                            })
                        if inspection.get("ragged_rows"):
                            issues.append({
                                "type": "ragged_rows",
                                "file_name": file_name,
                                "detail": f"{inspection['ragged_rows']} linha(s) com numero de colunas "
                                          "diferente do cabecalho",
                            })

                records.append(record)

    # comparacao de schema: dentro de cada (tour, categoria), usar o schema mais comum como referencia
    for (tour, category), entries in schemas_by_category.items():
        cols_lists = [cols for _, cols in entries]
        ref = validate.reference_schema(cols_lists)
        for file_name, cols in entries:
            if not cols:
                continue
            diff = validate.diff_columns(ref, cols)
            if not diff["matches_reference"]:
                issues.append({
                    "type": "schema_mismatch",
                    "file_name": file_name,
                    "detail": (
                        f"tour={tour} categoria={category} "
                        f"faltando={diff['missing_columns']} extras={diff['extra_columns']} "
                        f"ordem_diferente={diff['order_differs']}"
                    ),
                })

    manifest.write_json(records, issues, MANIFEST_JSON)
    manifest.write_markdown(records, issues, MANIFEST_MD)

    return {
        "records": records,
        "issues": issues,
        "repo_commit_sha": repo_commit_sha,
        "manifest_json": MANIFEST_JSON,
        "manifest_md": MANIFEST_MD,
    }


if __name__ == "__main__":
    result = run()
    print(f"Arquivos processados: {len(result['records'])}")
    print(f"Problemas detectados: {len(result['issues'])}")
    print(f"Manifesto: {result['manifest_json']}")
