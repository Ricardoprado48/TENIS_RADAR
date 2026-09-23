"""Download de arquivos brutos com hashing, sem sobrescrever silenciosamente."""

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from . import github_source
from .config import PROJECT_ROOT


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def fetch_and_store(
    *,
    repo: str,
    branch: str,
    remote_path: str,
    local_path: Path,
    repo_commit_sha: str,
    tour: str,
    category: str,
) -> dict:
    """Baixa um arquivo do GitHub e grava em local_path sem sobrescrever silenciosamente.

    Regras:
    - se local_path nao existe: grava e marca status=downloaded.
    - se local_path existe e o conteudo baixado e identico: status=skipped_identical
      (nao e sobrescrita, e um no-op idempotente).
    - se local_path existe e o conteudo baixado e diferente: NAO sobrescreve o
      arquivo original; grava o conteudo novo ao lado, com sufixo
      `.conflict-<timestamp>`, e marca status=conflict_manual_review_required.
    """
    collected_at = datetime.now(timezone.utc).isoformat()
    record = {
        "tour": tour,
        "category": category,
        "file_name": remote_path,
        "local_path": str(local_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "source_repo": repo,
        "source_branch": branch,
        "source_repo_commit_sha": repo_commit_sha,
        "collected_at_utc": collected_at,
    }

    meta = github_source.get_file_metadata(repo, branch, remote_path)
    if "error" in meta:
        record.update({
            "status": "missing",
            "error": meta["error"],
        })
        return record

    record["source_download_url"] = meta["download_url"]
    record["source_blob_sha"] = meta["sha"]
    record["source_reported_size_bytes"] = meta["size"]

    try:
        content = github_source.download_bytes(meta["download_url"])
    except Exception as exc:  # noqa: BLE001 - queremos registrar qualquer falha de rede
        record.update({"status": "missing", "error": f"download_failed: {exc}"})
        return record

    downloaded_sha256 = sha256_bytes(content)
    local_path.parent.mkdir(parents=True, exist_ok=True)

    if local_path.exists():
        existing_sha256 = sha256_file(local_path)
        if existing_sha256 == downloaded_sha256:
            record.update({
                "status": "skipped_identical",
                "sha256": existing_sha256,
                "size_bytes": local_path.stat().st_size,
            })
            return record
        else:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            conflict_path = local_path.with_name(f"{local_path.stem}.conflict-{ts}{local_path.suffix}")
            conflict_path.write_bytes(content)
            record.update({
                "status": "conflict_manual_review_required",
                "existing_sha256": existing_sha256,
                "downloaded_sha256": downloaded_sha256,
                "conflict_file": str(conflict_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            })
            return record

    local_path.write_bytes(content)
    record.update({
        "status": "downloaded",
        "sha256": downloaded_sha256,
        "size_bytes": local_path.stat().st_size,
    })
    return record
