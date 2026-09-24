"""Tennis Abstract Source para o LOTE J.

Coleta e faz cache local de dados estatísticos recentes do Tennis Abstract
respeitando rate limit (2.5s), cache com TTL (24h) e tratamento estrito
de erros (HTTP 429, 403, timeouts), sem bypass nem evasão.
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
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from . import config as cfg

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

PARSER_VERSION = "1.0.0"

# Schema canônico matchhead do Tennis Abstract (47 colunas)
MATCHHEAD_COLUMNS = [
    "date", "tourn", "surf", "level", "wl", "rank", "seed", "entry", "round",
    "score", "max", "opp", "orank", "oseed", "oentry", "ohand", "obday",
    "oht", "ocountry", "oactive", "time", "aces", "dfs", "pts", "firsts", "fwon",
    "swon", "games", "saved", "chances", "oaces", "odfs", "opts", "ofirsts",
    "ofwon", "oswon", "ogames", "osaved", "ochances", "obackhand", "chartlink",
    "pslink", "whserver", "matchid", "wh", "roundnum", "matchnum",
]


class TennisAbstractError(Exception):
    """Erro base para operações com Tennis Abstract."""


class RateLimitError(TennisAbstractError):
    """HTTP 429 recebido do Tennis Abstract."""


class AccessForbiddenError(TennisAbstractError):
    """HTTP 403 recebido do Tennis Abstract."""


class PlayerNotFoundError(TennisAbstractError):
    """Jogador não encontrado no Tennis Abstract."""


def slugify_player_name(name: str) -> str:
    """Normaliza o nome do jogador para o formato slug do Tennis Abstract (CamelCase sem espaços/acentos).

    Exemplo: 'Carlos Alcaraz' -> 'CarlosAlcaraz', 'Beatriz Haddad Maia' -> 'BeatrizHaddadMaia'
    """
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", ascii_only)
    return cleaned


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


class TennisAbstractSource:
    """Cliente HTTP com cache local e rate limit para Tennis Abstract."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        delay_seconds: float | None = None,
        ttl_hours: float | None = None,
    ) -> None:
        self.cache_dir = cache_dir or cfg.TA_CACHE_DIR
        self.delay_seconds = delay_seconds if delay_seconds is not None else cfg.TA_REQUEST_DELAY_SECONDS
        self.ttl_hours = ttl_hours if ttl_hours is not None else cfg.TA_CACHE_TTL_HOURS
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
            return data
        except Exception:
            return None

    def _write_cache(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _http_get(self, url: str) -> tuple[int, str]:
        self._rate_limit_sleep()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                content = resp.read().decode("utf-8", errors="ignore")
                return resp.status, content
        except urllib.error.HTTPError as exc:
            return exc.code, ""
        except Exception as exc:
            raise TennisAbstractError(f"Falha de conexão com {url}: {exc}") from exc

    def _extract_matchmx(self, html: str, tour: str, slug: str) -> tuple[str, list[list[str]]]:
        # 1. Tenta inline
        m = re.search(r"var\s+matchmx\s*=\s*\[(.*?)\];", html, re.DOTALL)
        if m:
            text = m.group(1).strip()
            if text:
                return text, parse_js_matrix(text)

        # 2. Tenta script externo referenciado na página
        js_match = re.search(r'src=["\'](https?://[^"\']*/jsmatches/[^"\']*\.js)["\']', html)
        if js_match:
            js_url = js_match.group(1)
            status, js_code = self._http_get(js_url)
            if status == 200:
                m_js = re.search(r"var\s+matchmx\s*=\s*\[(.*?)\];", js_code, re.DOTALL)
                if m_js:
                    return m_js.group(1).strip(), parse_js_matrix(m_js.group(1).strip())

        # 3. Fallback: URL direta padrão do jsmatches
        direct_js_url = f"https://www.tennisabstract.com/jsmatches/{slug}.js"
        try:
            status, js_code = self._http_get(direct_js_url)
            if status == 200:
                m_js = re.search(r"var\s+matchmx\s*=\s*\[(.*?)\];", js_code, re.DOTALL)
                if m_js:
                    return m_js.group(1).strip(), parse_js_matrix(m_js.group(1).strip())
        except Exception:
            pass

        return "", []

    def fetch_player_matches(
        self,
        player_name: str,
        tour: str,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Busca partidas de um jogador no Tennis Abstract.

        Retorna dicionário contendo os dados brutos, partidas parsed e metadados de cache.
        """
        tour_clean = tour.upper()
        if tour_clean not in ("ATP", "WTA"):
            raise ValueError(f"Tour inválido: {tour}. Use 'ATP' ou 'WTA'.")

        slug = slugify_player_name(player_name)
        if not slug:
            raise ValueError(f"Nome do jogador inválido ou vazio: {player_name}")

        cache_path = self._get_cache_path(tour_clean, slug)

        if not force_refresh:
            cached = self._read_cache(cache_path)
            if cached is not None:
                cached["cache_hit"] = True
                return cached

        # Montar URL pública
        if tour_clean == "ATP":
            url = f"http://www.tennisabstract.com/cgi-bin/player-classic.cgi?p={slug}"
        else:
            url = f"http://www.tennisabstract.com/cgi-bin/wplayer-classic.cgi?p={slug}"

        status, html = self._http_get(url)

        if status == 429:
            raise RateLimitError("HTTP 429: Tennis Abstract retornou rate limit.")
        if status == 403:
            raise AccessForbiddenError("HTTP 403: Acesso negado ao Tennis Abstract.")
        if status == 404 or (status == 200 and not html):
            raise PlayerNotFoundError(f"Jogador não encontrado: {player_name} ({slug})")
        if status != 200:
            raise TennisAbstractError(f"HTTP {status} ao consultar {url}")

        raw_js, rows = self._extract_matchmx(html, tour_clean, slug)

        parsed_matches: list[dict[str, str]] = []
        for r in rows:
            m_dict: dict[str, str] = {}
            for idx, col_name in enumerate(MATCHHEAD_COLUMNS):
                m_dict[col_name] = r[idx] if idx < len(r) else ""
            parsed_matches.append(m_dict)

        content_hash = hashlib.sha256(raw_js.encode("utf-8")).hexdigest() if raw_js else ""
        fetched_at = datetime.now(timezone.utc).isoformat()

        payload = {
            "player": {
                "name": player_name,
                "slug": slug,
                "tour": tour_clean,
            },
            "fetched_at": fetched_at,
            "source_url": url,
            "hash": content_hash,
            "parser_version": PARSER_VERSION,
            "total_matches": len(parsed_matches),
            "matches": parsed_matches,
            "cache_hit": False,
        }

        self._write_cache(cache_path, payload)
        return payload

