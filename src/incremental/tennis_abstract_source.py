"""Tennis Abstract Source para o LOTE J.

Coleta e faz cache local de dados estatísticos recentes do Tennis Abstract
respeitando rate limit (2.5s), cache com TTL (24h) e tratamento estrito
de erros (HTTP 429, 403, timeouts), sem bypass nem evasão.

Regras comprovadas no preflight T2 (2026-09-24):
- o slug é sensível a maiúsculas: CamelCase do nome canônico de players.parquet
  ("Bu Yunchaokete" -> BuYunchaokete); exceções só via `ta_slug_overrides.csv`;
- slug inválido responde HTTP 200 com uma página modelo sem `var fullname` e
  sem `matchmx` -> o critério é a ausência desses marcadores, não o 404;
- somente a página principal é requisitada: nenhuma URL secundária
  (`/jsmatches/{slug}.js`) é buscada automaticamente, e nenhum retry.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from . import config as cfg

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

PARSER_VERSION = "1.1.0"

SLUG_OVERRIDES_PATH = Path(__file__).with_name("ta_slug_overrides.csv")
SLUG_OVERRIDE_COLUMNS = ["player_id", "slug", "reason"]

# Classificação da resposta da página principal
PAGE_OK = "PAGE_OK"                # fullname e/ou matchmx com partidas
EMPTY_PAGE = "EMPTY_PAGE"          # fullname presente, matchmx sem partidas
NO_PLAYER_DATA = "NO_PLAYER_DATA"  # sem fullname e sem matchmx (página modelo)
HTTP_403 = "HTTP_403"
HTTP_429 = "HTTP_429"
HTTP_ERROR = "HTTP_ERROR"          # qualquer outro status != 200 (inclui 404)
NETWORK_ERROR = "NETWORK_ERROR"
CACHEABLE_STATUSES = (PAGE_OK, EMPTY_PAGE)

# Schema canônico matchhead do Tennis Abstract (47 colunas)
MATCHHEAD_COLUMNS = [
    "date", "tourn", "surf", "level", "wl", "rank", "seed", "entry", "round",
    "score", "max", "opp", "orank", "oseed", "oentry", "ohand", "obday",
    "oht", "ocountry", "oactive", "time", "aces", "dfs", "pts", "firsts", "fwon",
    "swon", "games", "saved", "chances", "oaces", "odfs", "opts", "ofirsts",
    "ofwon", "oswon", "ogames", "osaved", "ochances", "obackhand", "chartlink",
    "pslink", "whserver", "matchid", "wh", "roundnum", "matchnum",
]

_MATCHMX_RE = re.compile(r"var\s+matchmx\s*=\s*\[(.*?)\];", re.DOTALL)
_FULLNAME_RE = re.compile(r"var\s+fullname\s*=\s*(['\"])(.*?)\1")


class TennisAbstractError(Exception):
    """Erro base para operações com Tennis Abstract."""


class RateLimitError(TennisAbstractError):
    """HTTP 429 recebido do Tennis Abstract."""

    def __init__(self, message: str, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class AccessForbiddenError(TennisAbstractError):
    """HTTP 403 recebido do Tennis Abstract."""


class PlayerNotFoundError(TennisAbstractError):
    """Página sem marcadores de jogador (sem `var fullname` e sem `matchmx`)."""


class NetworkError(TennisAbstractError):
    """Falha de conexão/timeout antes de obter status HTTP."""

    def __init__(self, message: str, timeout: bool = False) -> None:
        super().__init__(message)
        self.timeout = timeout


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    return isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, TimeoutError)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: str
    headers: dict[str, str] = field(default_factory=dict)

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())


@dataclass(frozen=True)
class PageClassification:
    fetch_status: str
    page_fullname: str | None
    raw_js: str
    rows: list[list[str]]


def slugify_player_name(name: str) -> str:
    """Normaliza o nome do jogador para o formato slug do Tennis Abstract (CamelCase sem espaços/acentos).

    Exemplo: 'Carlos Alcaraz' -> 'CarlosAlcaraz', 'Beatriz Haddad Maia' -> 'BeatrizHaddadMaia'
    """
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", ascii_only)
    return cleaned


def load_slug_overrides(path: Path | None = None) -> dict[str, str]:
    """{player_id: slug} do CSV versionado. Arquivo ausente => sem overrides.
    Schema inválido, player_id duplicado ou slug vazio/com espaço => ValueError."""
    path = path or SLUG_OVERRIDES_PATH
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != SLUG_OVERRIDE_COLUMNS:
            raise ValueError(f"{path}: cabeçalho esperado {SLUG_OVERRIDE_COLUMNS}, recebido {reader.fieldnames}")
        overrides: dict[str, str] = {}
        for rec in reader:
            pid, slug = (rec["player_id"] or "").strip(), (rec["slug"] or "").strip()
            if not pid or not slug or re.search(r"\s", slug):
                raise ValueError(f"{path}: linha inválida {rec}")
            if pid in overrides:
                raise ValueError(f"{path}: player_id duplicado {pid}")
            overrides[pid] = slug
    return overrides


def resolve_slug(
    player_id: str,
    player_name: str,
    overrides: dict[str, str] | None = None,
    explicit_slug: str | None = None,
) -> tuple[str, str]:
    """(slug, slug_source): explícito > override por player_id > CamelCase do nome canônico."""
    if explicit_slug:
        return explicit_slug, "explicit"
    if overrides is None:
        overrides = load_slug_overrides()
    if player_id in overrides:
        return overrides[player_id], "override"
    slug = slugify_player_name(player_name)
    if not slug:
        raise ValueError(f"Nome do jogador inválido ou vazio: {player_name!r}")
    return slug, "generated"


def parse_js_matrix(matrix_text: str) -> list[list[str]]:
    """Converte o corpo do array JS matchmx em lista de listas Python."""
    rows: list[list[str]] = []
    raw_rows = re.findall(r"\[(.*?)\]", matrix_text, re.DOTALL)
    for r in raw_rows:
        reader = csv.reader([r.strip()], quotechar='"', skipinitialspace=True)
        try:
            row = next(reader)
            if row:
                rows.append([c.strip() for c in row])
        except Exception:
            continue
    return rows


def classify_player_page(html: str) -> PageClassification:
    """Classifica o HTML (status 200) da página principal, somente por marcadores."""
    fullname_m = _FULLNAME_RE.search(html or "")
    fullname = fullname_m.group(2).strip() or None if fullname_m else None
    mx = _MATCHMX_RE.search(html or "")
    raw_js = mx.group(1).strip() if mx else ""
    rows = parse_js_matrix(raw_js) if raw_js else []
    if rows:
        status = PAGE_OK
    elif fullname:
        status = EMPTY_PAGE
    else:
        status = NO_PLAYER_DATA
    return PageClassification(status, fullname, raw_js, rows)


def _rows_to_matches(rows: list[list[str]]) -> list[dict[str, str]]:
    return [
        {col: (r[idx] if idx < len(r) else "") for idx, col in enumerate(MATCHHEAD_COLUMNS)}
        for r in rows
    ]


class TennisAbstractSource:
    """Cliente HTTP com cache local e rate limit para Tennis Abstract."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        delay_seconds: float | None = None,
        ttl_hours: float | None = None,
        slug_overrides: dict[str, str] | None = None,
    ) -> None:
        self.cache_dir = cache_dir or cfg.TA_CACHE_DIR
        self.delay_seconds = delay_seconds if delay_seconds is not None else cfg.TA_REQUEST_DELAY_SECONDS
        self.ttl_hours = ttl_hours if ttl_hours is not None else cfg.TA_CACHE_TTL_HOURS
        self.slug_overrides = slug_overrides
        self._last_request_time: float = 0.0

    def _rate_limit_sleep(self) -> None:
        """Garante intervalo de cortesia mínimo entre chamadas HTTP reais."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)
        self._last_request_time = time.time()

    def _get_cache_path(self, tour: str, slug: str) -> Path:
        return self.cache_dir / tour.upper() / f"{slug}.json"

    def _read_cache(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            fetched_at_str = data.get("fetched_at")
            if not fetched_at_str:
                return None
            fetched_at = datetime.fromisoformat(fetched_at_str)
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if (now - fetched_at) > timedelta(hours=self.ttl_hours):
                return None  # Cache expirado
            # cache anterior à classificação (v1.0) com 0 partidas pode ser uma
            # página modelo de slug inválido: não confiável
            if data.get("fetch_status") not in CACHEABLE_STATUSES and not data.get("matches"):
                return None
            return data
        except Exception:
            return None

    def _write_cache(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _http_get(self, url: str) -> HttpResponse:
        """Uma única requisição GET, sem retry. Falha de rede => NetworkError."""
        self._rate_limit_sleep()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                content = resp.read().decode("utf-8", errors="ignore")
                return HttpResponse(resp.status, content, {k.lower(): v for k, v in resp.headers.items()})
        except urllib.error.HTTPError as exc:
            headers = {k.lower(): v for k, v in (exc.headers or {}).items()}
            try:
                body = exc.read().decode("utf-8", errors="ignore")
            except Exception:
                body = ""
            return HttpResponse(exc.code, body, headers)
        except Exception as exc:
            raise NetworkError(f"Falha de conexão com {url}: {exc}", timeout=_is_timeout(exc)) from exc

    @staticmethod
    def player_url(tour: str, slug: str) -> str:
        if tour == "ATP":
            return f"http://www.tennisabstract.com/cgi-bin/player-classic.cgi?p={slug}"
        return f"http://www.tennisabstract.com/cgi-bin/wplayer-classic.cgi?p={slug}"

    def fetch_player_page(
        self,
        player_id: str,
        player_name: str,
        tour: str,
        slug: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Busca a página principal de um jogador de `player_id` já conhecido.

        Nunca levanta exceção por status HTTP: o resultado sempre traz
        `fetch_status` (PAGE_OK, EMPTY_PAGE, NO_PLAYER_DATA, HTTP_403,
        HTTP_429, HTTP_ERROR, NETWORK_ERROR), `http_status` e `retry_after`.
        No máximo 1 requisição HTTP; só PAGE_OK/EMPTY_PAGE vão para o cache."""
        tour_clean = tour.upper()
        if tour_clean not in ("ATP", "WTA"):
            raise ValueError(f"Tour inválido: {tour}. Use 'ATP' ou 'WTA'.")
        if not player_id:
            raise ValueError("player_id obrigatório")

        overrides = self.slug_overrides if self.slug_overrides is not None else load_slug_overrides()
        slug, slug_source = resolve_slug(player_id, player_name, overrides, explicit_slug=slug)
        player = {"player_id": player_id, "name": player_name, "slug": slug,
                  "slug_source": slug_source, "tour": tour_clean}
        url = self.player_url(tour_clean, slug)
        cache_path = self._get_cache_path(tour_clean, slug)

        if not force_refresh:
            cached = self._read_cache(cache_path)
            if cached is not None:
                cached.setdefault("fetch_status", PAGE_OK if cached.get("matches") else EMPTY_PAGE)
                cached.setdefault("http_status", 200)
                cached.setdefault("retry_after", None)
                cached.setdefault("page_fullname", None)
                cached.setdefault("error", None)
                cached.setdefault("error_code", None)
                cached["player"] = {**cached.get("player", {}), **player}
                cached["cache_hit"] = True
                return cached

        result: dict[str, Any] = {
            "player": player,
            "fetch_status": None,
            "http_status": None,
            "retry_after": None,
            "page_fullname": None,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source_url": url,
            "hash": "",
            "parser_version": PARSER_VERSION,
            "total_matches": 0,
            "matches": [],
            "cache_hit": False,
            "error": None,
            "error_code": None,
        }
        try:
            resp = self._http_get(url)
        except NetworkError as exc:
            result.update(fetch_status=NETWORK_ERROR, error=str(exc),
                          error_code="TIMEOUT" if exc.timeout else NETWORK_ERROR)
            return result

        result["http_status"] = resp.status
        result["retry_after"] = resp.header("retry-after")
        if resp.status == 429:
            result["fetch_status"] = HTTP_429
            return result
        if resp.status == 403:
            result["fetch_status"] = HTTP_403
            return result
        if resp.status != 200:
            result["fetch_status"] = HTTP_ERROR
            return result

        page = classify_player_page(resp.body)
        matches = _rows_to_matches(page.rows)
        result.update(
            fetch_status=page.fetch_status,
            page_fullname=page.page_fullname,
            hash=hashlib.sha256(page.raw_js.encode("utf-8")).hexdigest() if page.raw_js else "",
            total_matches=len(matches),
            matches=matches,
        )
        if page.fetch_status in CACHEABLE_STATUSES:
            self._write_cache(cache_path, result)
        return result

    def fetch_player_matches(
        self,
        player_name: str,
        tour: str,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Interface legada (por nome, sem player_id): levanta exceção em vez de
        classificar. Mesma regra de página única, sem URL secundária."""
        tour_clean = tour.upper()
        if tour_clean not in ("ATP", "WTA"):
            raise ValueError(f"Tour inválido: {tour}. Use 'ATP' ou 'WTA'.")

        slug = slugify_player_name(player_name)
        if not slug:
            raise ValueError(f"Nome do jogador inválido ou vazio: {player_name}")

        result = self.fetch_player_page(f"UNRESOLVED:{slug}", player_name, tour_clean,
                                         slug=slug, force_refresh=force_refresh)
        status = result["fetch_status"]
        if status == HTTP_429:
            raise RateLimitError("HTTP 429: Tennis Abstract retornou rate limit.", result["retry_after"])
        if status == HTTP_403:
            raise AccessForbiddenError("HTTP 403: Acesso negado ao Tennis Abstract.")
        if status == NO_PLAYER_DATA:
            raise PlayerNotFoundError(f"Página sem dados de jogador: {player_name} ({slug})")
        if status == NETWORK_ERROR:
            raise NetworkError(result["error"], timeout=result["error_code"] == "TIMEOUT")
        if status == HTTP_ERROR:
            raise TennisAbstractError(f"HTTP {result['http_status']} ao consultar {result['source_url']}")
        result["player"] = {"name": player_name, "slug": slug, "tour": tour_clean}
        return result
