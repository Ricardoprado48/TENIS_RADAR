"""Escrita do manifesto de ingestao (JSON + resumo Markdown)."""

import json
from datetime import datetime, timezone
from pathlib import Path


def write_json(records: list, issues: list, path: Path) -> None:
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_files": len(records),
        "n_issues": len(issues),
        "files": records,
        "issues": issues,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_markdown(records: list, issues: list, path: Path) -> None:
    lines = [
        "# Manifesto de ingestao — Fase 1",
        "",
        f"Gerado em: {datetime.now(timezone.utc).isoformat()}",
        f"Arquivos processados: {len(records)}",
        f"Problemas detectados: {len(issues)}",
        "",
        "| Tour | Categoria | Arquivo | Status | Linhas | Colunas | Tamanho (bytes) | SHA256 |",
        "|---|---|---|---|---:|---:|---:|---|",
    ]
    for r in records:
        lines.append(
            "| {tour} | {category} | {file_name} | {status} | {n_rows} | {n_cols} | {size_bytes} | {sha} |".format(
                tour=r.get("tour", ""),
                category=r.get("category", ""),
                file_name=r.get("file_name", ""),
                status=r.get("status", ""),
                n_rows=r.get("n_rows", ""),
                n_cols=r.get("n_cols", ""),
                size_bytes=r.get("size_bytes", ""),
                sha=(r.get("sha256") or r.get("existing_sha256") or "")[:12],
            )
        )

    lines.append("")
    lines.append("## Problemas")
    lines.append("")
    if not issues:
        lines.append("Nenhum problema detectado.")
    else:
        for issue in issues:
            lines.append(f"- **{issue['type']}** — {issue['file_name']} ({issue.get('detail', '')})")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
