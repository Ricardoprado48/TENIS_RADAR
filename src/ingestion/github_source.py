"""Cliente minimo para a GitHub Contents API (somente leitura, sem dependencias externas)."""

import json
import urllib.error
import urllib.request

API_ROOT = "https://api.github.com"
USER_AGENT = "tennis-radar-ingestion/0.1 (+https://github.com)"


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_file_metadata(repo: str, branch: str, path: str) -> dict:
    """Retorna metadados de um arquivo no repo via GitHub Contents API.

    Campos relevantes: name, download_url, sha (git blob sha), size.
    """
    url = f"{API_ROOT}/repos/{repo}/contents/{path}?ref={branch}"
    try:
        data = _get_json(url)
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}", "path": path}
    if isinstance(data, list):
        return {"error": "path aponta para um diretorio, nao arquivo", "path": path}
    return {
        "name": data.get("name"),
        "path": data.get("path"),
        "download_url": data.get("download_url"),
        "sha": data.get("sha"),
        "size": data.get("size"),
    }


def get_branch_head_commit(repo: str, branch: str) -> str:
    """Retorna o SHA do commit HEAD da branch (para registrar a versao da fonte)."""
    url = f"{API_ROOT}/repos/{repo}/branches/{branch}"
    try:
        data = _get_json(url)
    except urllib.error.HTTPError as exc:
        return f"error:HTTP {exc.code}"
    return data.get("commit", {}).get("sha", "unknown")


def download_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()
