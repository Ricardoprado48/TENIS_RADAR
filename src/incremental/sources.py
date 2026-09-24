"""Investigacao de fontes para a atualizacao incremental (item 1 da instrucao).

Segue a ordem de prioridade do enunciado da Fase 8.1:
  1. dataset estruturado;
  2. mirror atualizado do Sackmann;
  3. GitHub/repositorio equivalente confiavel;
  4. fonte HTTP estruturada;
  5. Tennis Abstract;
  6. Firecrawl somente se necessario;
  7. browser automation somente como ultimo recurso.

Cada `check_*`/`evaluate_*` recebe as funcoes de rede por parametro (com um
default que faz a chamada real), para poder ser testado sem depender de
rede -- mesmo padrao de `tests/test_ingestion.py` para
`src.ingestion.github_source` (mock.patch nas funcoes de baixo nivel).

`run_source_investigation()` executa a investigacao real (rede ao vivo) e
grava a evidencia em `data/raw/incremental_2026/` -- e o resultado dessa
funcao, rodada em 2026-09-22, que fundamenta a conclusao registrada em
docs/014 de que nenhuma fonte disponivel cobre integralmente o schema
historico (estatisticas de saque/devolucao) para o periodo 2026-05-26 a
2026-09-22 sem contornar bloqueio anti-bot ou sem exigir scraping manual em
larga escala (ver docstring de `run_source_investigation`).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field

import pandas as pd

from src.ingestion import github_source as gh
from src.normalization.config import SOURCES

from . import config as cfg
from .tennis_abstract_source import (  # noqa: F401
    TennisAbstractSource,
    RateLimitError,
    AccessForbiddenError,
    PlayerNotFoundError,
)

ORIGINAL_REPOS = {
    "atp": "JeffSackmann/tennis_atp",
    "wta": "JeffSackmann/tennis_wta",
}

MIRROR_REPO = "Aneeshers/tennis-sackmann-archive"
MIRROR_BRANCH = "main"
MIRROR_FILES = {"atp": "atp/atp_matches_2026.csv", "wta": "wta/wta_matches_2026.csv"}

# candidatos encontrados via busca no GitHub (2026-09-22) que pareciam, pelo
# nome/descricao, poder conter resultados ATP/WTA recentes -- avaliados
# quanto a compatibilidade de schema (nao apenas descricao).
CANDIDATE_REPOS = [
    {"repo": "abbygracemorrow/ATP-data", "sample_path": "data/atp_matches.csv", "tour": "atp",
     "note": "derivado do dataset Kaggle dissfya/atp-tennis-2000-2023daily-pull (atualizado diariamente)"},
    {"repo": "Mriganka-codes/tennis_data", "sample_path": "matches.json", "tour": "both",
     "note": "scraper de tennisexplorer.com com odds -- fora de escopo (item final: nao coletar odds)"},
]

# endpoints HTTP diretos (oficiais) testados com cliente simples (sem
# navegador), para confirmar se o bloqueio anti-bot documentado na Fase 8
# (docs/013 secao 1) ainda se aplica.
DIRECT_HTTP_ENDPOINTS = [
    "https://www.atptour.com/en/-/www/rankings/singles?rankRange=1-100",
    "https://www.atptour.com/-/Hawkeye/MatchStats/Complete/2026/580/MS001",
    "https://www.espn.com/tennis/player/results/_/id/3340/sebastian-baez",
]

# Classificacao de conteudo obtida por investigacao manual nesta mesma
# sessao (WebFetch, 2026-09-22): estas URLs respondem a um cliente HTTP
# simples, mas expoem somente placar/rodada/adversario -- nenhuma
# estatistica de saque/devolucao (aces, double faults, service points, ...).
# Ver docs/014 secao 1 para o registro completo.
SCORE_ONLY_ENDPOINTS = {
    "https://www.espn.com/tennis/player/results/_/id/3340/sebastian-baez",
}


@dataclass
class SourceCheckResult:
    source: str
    priority_tier: int
    status: str  # "adequate" | "inadequate_schema" | "unavailable" | "out_of_scope"
    reason: str
    evidence: dict = field(default_factory=dict)


def _http_status(url: str) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": gh.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception as exc:  # timeout, DNS, etc. -- registra como evidencia, nao derruba a investigacao
        return -1


def _github_repo_status(repo: str) -> int:
    req = urllib.request.Request(
        f"{gh.API_ROOT}/repos/{repo}",
        headers={"User-Agent": gh.USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def check_original_sackmann_repos(status_fn=_github_repo_status) -> list[SourceCheckResult]:
    """item 1/prioridade 2: os repositorios originais ainda existem/foram
    atualizados desde a Fase 1?"""

    out = []
    for tour, repo in ORIGINAL_REPOS.items():
        code = status_fn(repo)
        if code == 200:
            out.append(SourceCheckResult(repo, 2, "adequate", "repositorio original disponivel novamente", {"http_status": code}))
        else:
            out.append(SourceCheckResult(
                repo, 2, "unavailable",
                f"HTTP {code} ao consultar api.github.com/repos/{repo} -- repositorio original indisponivel",
                {"http_status": code, "tour": tour.upper()},
            ))
    return out


def _known_mirror_shas() -> dict:
    """Le (somente leitura) os shas registrados pela Fase 1 em
    data/raw/ingestion_manifest.json para comparar com o estado atual do
    mirror -- nunca sobrescreve esse arquivo."""

    manifest_path = cfg.DATA_RAW / "ingestion_manifest.json"
    if not manifest_path.exists():
        return {}
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    out = {}
    for entry in data.get("files", []):
        if entry.get("file_name") in MIRROR_FILES.values():
            out[entry["file_name"]] = {
                "commit_sha": entry.get("source_repo_commit_sha"),
                "blob_sha": entry.get("source_blob_sha"),
            }
    return out


def check_mirror_freshness(head_commit_fn=None, file_meta_fn=None) -> SourceCheckResult:
    """item 1/prioridade 2: o mirror usado na Fase 1 (Aneeshers/tennis-sackmann-archive)
    recebeu commits novos desde a ingestao original?"""

    head_commit_fn = head_commit_fn or (lambda: gh.get_branch_head_commit(MIRROR_REPO, MIRROR_BRANCH))
    file_meta_fn = file_meta_fn or (lambda path: gh.get_file_metadata(MIRROR_REPO, MIRROR_BRANCH, path))

    known = _known_mirror_shas()
    current_head = head_commit_fn()
    current_files = {path: file_meta_fn(path) for path in MIRROR_FILES.values()}

    unchanged = all(
        known.get(path, {}).get("blob_sha") == current_files[path].get("sha")
        for path in MIRROR_FILES.values()
        if path in known
    )

    evidence = {
        "known_head_commit": next(iter({v["commit_sha"] for v in known.values() if v.get("commit_sha")}), None),
        "current_head_commit": current_head,
        "files": {
            path: {
                "known_blob_sha": known.get(path, {}).get("blob_sha"),
                "current_blob_sha": current_files[path].get("sha"),
                "current_size": current_files[path].get("size"),
            }
            for path in MIRROR_FILES.values()
        },
    }

    if unchanged and known:
        return SourceCheckResult(
            MIRROR_REPO, 2, "unavailable",
            "mirror sem commits novos desde a ingestao da Fase 1 (mesmo commit/blob sha) -- "
            "nao cobre o periodo 2026-05-26 em diante",
            evidence,
        )
    return SourceCheckResult(
        MIRROR_REPO, 2, "adequate" if known else "unavailable",
        "mirror foi atualizado desde a Fase 1" if not unchanged else "sem registro previo para comparar",
        evidence,
    )


def evaluate_candidate_repo(repo: str, sample_path: str, header_fetch_fn=None) -> SourceCheckResult:
    """item 1/prioridade 3: baixa a primeira linha (cabecalho) do arquivo
    amostra do repositorio candidato e verifica quais colunas exigidas por
    `src.normalization.matches.transform_raw_matches` estao presentes --
    decisao por schema real, nao por descricao do README."""

    header_fetch_fn = header_fetch_fn or (lambda r, p: _fetch_first_line(r, p))
    try:
        header_line = header_fetch_fn(repo, sample_path)
    except Exception as exc:
        return SourceCheckResult(repo, 3, "unavailable", f"falha ao buscar {sample_path}: {exc}", {"sample_path": sample_path})

    if header_line.strip().startswith("{") or header_line.strip().startswith("["):
        return SourceCheckResult(
            repo, 3, "inadequate_schema",
            f"{sample_path} nao e um CSV tabular (formato JSON) -- nao compativel diretamente com o schema Sackmann",
            {"sample_path": sample_path, "header_preview": header_line[:200]},
        )

    columns = [c.strip() for c in header_line.strip().split(",")]
    missing_stat_cols = [c for c in cfg.STAT_COLUMNS if c not in columns]
    missing_schema_cols = [c for c in cfg.RAW_SCHEMA_COLUMNS if c not in columns]

    if not missing_schema_cols:
        status, reason = "adequate", "todas as colunas do schema historico presentes"
    elif not missing_stat_cols:
        status, reason = "adequate", "estatisticas de saque presentes; colunas de contexto faltantes sao derivaveis"
    else:
        status, reason = (
            "inadequate_schema",
            f"faltam {len(missing_stat_cols)}/{len(cfg.STAT_COLUMNS)} colunas de estatisticas de saque/devolucao "
            f"(ex.: {missing_stat_cols[:5]}) -- fonte de resultado (score), nao de estatisticas",
        )

    return SourceCheckResult(repo, 3, status, reason, {
        "sample_path": sample_path,
        "columns_found": columns,
        "missing_stat_columns": missing_stat_cols,
        "missing_schema_columns": missing_schema_cols,
    })


def _fetch_first_line(repo: str, path: str) -> str:
    url = f"https://raw.githubusercontent.com/{repo}/main/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": gh.USER_AGENT, "Range": "bytes=0-4000"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        chunk = resp.read().decode("utf-8", errors="replace")
    return chunk.splitlines()[0] if chunk else ""


def check_direct_http_endpoints(urls: list[str] = None, status_fn=_http_status) -> list[SourceCheckResult]:
    """item 1/prioridade 4: os endpoints oficiais ATP/WTA/ESPN respondem a
    um cliente HTTP simples (sem navegador)? Confirma (ou nao) o bloqueio
    anti-bot documentado na Fase 8 (docs/013 secao 1)."""

    urls = urls or DIRECT_HTTP_ENDPOINTS
    out = []
    for url in urls:
        code = status_fn(url)
        blocked = code in (403, 429) or code == -1
        if blocked:
            status = "unavailable"
            reason = f"HTTP {code} -- bloqueado (anti-bot ou indisponivel)"
        elif url in SCORE_ONLY_ENDPOINTS:
            status = "inadequate_schema"
            reason = (
                f"HTTP {code} -- acessivel, mas fornece somente placar/rodada/adversario "
                "(sem aces, double faults, service points, ...)"
            )
        else:
            status = "adequate"
            reason = f"HTTP {code} -- acessivel"
        out.append(SourceCheckResult(url, 4, status, reason, {"http_status": code}))
    return out


def run_source_investigation() -> dict:
    """Executa a investigacao completa (rede ao vivo) e grava evidencia em
    data/raw/incremental_2026/. Resultado real, obtido em 2026-09-22:

      - repositorios originais JeffSackmann/tennis_atp e tennis_wta: HTTP 404
        (mesma conclusao da Fase 1/config.py, reconfirmada).
      - mirror Aneeshers/tennis-sackmann-archive: mesmo commit/blob sha
        gravado na ingestao da Fase 1 -- nao recebeu atualizacao alguma.
      - abbygracemorrow/ATP-data (derivado de dataset Kaggle "daily-pull"):
        schema real tem 13 colunas (Tournament, Date, Surface, Round, Player_1,
        Player_2, Winner, Rank_1, Rank_2, Score, ...) -- SEM nenhuma das 18
        colunas de estatisticas de saque/devolucao exigidas; alem disso e
        somente ATP.
      - Mriganka-codes/tennis_data: formato JSON (nao tabular Sackmann),
        cobre so "partidas de hoje" (nao historico), e inclui odds de
        tennisexplorer.com -- fora de escopo por instrucao explicita ("nao
        coletar odds").
      - endpoints diretos ATP Tour: HTTP 403 (bloqueio anti-bot Akamai,
        mesma conclusao da Fase 8). ESPN (paginas de resultado por jogador)
        e acessivel a um cliente HTTP simples, mas fornece somente
        placar/rodada/adversario -- nenhuma estatistica de saque.

    Conclusao: nenhuma fonte investigada fornece, de forma estruturada e sem
    contornar bloqueio anti-bot, as estatisticas de saque/devolucao
    exigidas pelo schema historico para partidas depois de 2026-05-25. Ver
    docs/014 para a decisao e as implicacoes."""

    results: list[SourceCheckResult] = []
    results += check_original_sackmann_repos()
    results.append(check_mirror_freshness())
    for cand in CANDIDATE_REPOS:
        results.append(evaluate_candidate_repo(cand["repo"], cand["sample_path"]))
    results += check_direct_http_endpoints()

    adequate = [r for r in results if r.status == "adequate"]

    verdict = {
        "checked_at_utc": str(pd.Timestamp.now("UTC")),
        "n_sources_checked": len(results),
        "n_adequate": len(adequate),
        "adequate_source_found": len(adequate) > 0,
        "selected_source": adequate[0].source if adequate else None,
        "results": [asdict(r) for r in results],
    }

    cfg.INCREMENTAL_RAW_DIR.mkdir(parents=True, exist_ok=True)
    cfg.INVESTIGATION_JSON.write_text(json.dumps(verdict, indent=2, default=str), encoding="utf-8")

    lines = ["# Investigacao de fontes -- Fase 8.1", "", f"Checado em: {verdict['checked_at_utc']}", ""]
    lines.append("| fonte | prioridade | status | motivo |")
    lines.append("|---|---|---|---|")
    for r in results:
        lines.append(f"| {r.source} | {r.priority_tier} | {r.status} | {r.reason} |")
    lines.append("")
    lines.append(f"**Fonte adequada encontrada:** {'sim -> ' + adequate[0].source if adequate else 'nao'}")
    cfg.INVESTIGATION_MD.write_text("\n".join(lines), encoding="utf-8")

    return verdict
