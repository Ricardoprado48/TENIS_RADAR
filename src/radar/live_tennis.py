"""Cliente mínimo da Live Tennis API para agenda operacional do Radar.

Escopo desta camada:
- autenticar com LIVETENNISAPI_KEY;
- consultar partidas `upcoming` de simples ATP/WTA;
- consultar `fixtures` somente como metadado de agenda (principalmente
  `event_date`, que não existe no objeto Match);
- paginar sem depender do SDK oficial;
- retornar payloads brutos para a etapa de normalização.

Nenhuma probabilidade, ranking, mercado ou análise da Live Tennis entra no
modelo do Tennis Radar por esta camada.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

BASE_URL = "https://api.livetennisapi.com/api/public/v1"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUPPORTED_TOURS = {"ATP": "atp", "WTA": "wta"}


class LiveTennisAPIError(RuntimeError):
    """Falha de contrato, autenticação ou resposta da Live Tennis API."""


class LiveTennisClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        if api_key is None:
            load_dotenv(PROJECT_ROOT / ".env")
            api_key = os.getenv("LIVETENNISAPI_KEY")

        key = (api_key or "").strip()
        if not key:
            raise LiveTennisAPIError(
                "LIVETENNISAPI_KEY ausente. Configure a chave no arquivo .env do projeto."
            )

        self._api_key = key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "User-Agent": "TENNIS_RADAR/1.0",
        }

    def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self.session.get(
                url,
                headers=self._headers(),
                params=params,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise LiveTennisAPIError(f"falha ao consultar Live Tennis API: {exc}") from exc

        if not 200 <= response.status_code < 300:
            raise LiveTennisAPIError(
                f"Live Tennis API retornou HTTP {response.status_code} em {path}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise LiveTennisAPIError("Live Tennis API retornou JSON inválido") from exc

        if not isinstance(payload, dict):
            raise LiveTennisAPIError("Live Tennis API retornou payload fora do contrato esperado")
        return payload

    def _list_paginated(
        self,
        path: str,
        *,
        tour: str,
        page_size: int,
        extra_params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        tour_key = tour.upper().strip()
        if tour_key not in SUPPORTED_TOURS:
            raise ValueError(f"tour inválido: {tour!r}; esperado ATP ou WTA")
        if page_size < 1 or page_size > 50:
            raise ValueError("page_size deve ficar entre 1 e 50")

        api_tour = SUPPORTED_TOURS[tour_key]
        offset = 0
        collected: list[dict[str, Any]] = []

        while True:
            params: dict[str, Any] = {
                "tour": api_tour,
                "draw": "singles",
                "limit": page_size,
                "offset": offset,
            }
            if extra_params:
                params.update(extra_params)

            payload = self._get_json(path, params)
            data = payload.get("data")
            meta = payload.get("meta")
            if not isinstance(data, list) or not isinstance(meta, dict):
                raise LiveTennisAPIError(
                    "Live Tennis API retornou data/meta fora do contrato esperado"
                )

            for row in data:
                if not isinstance(row, dict):
                    raise LiveTennisAPIError(
                        "Live Tennis API retornou registro fora do contrato esperado"
                    )
                collected.append(row)

            if not bool(meta.get("has_more")):
                break

            if not data:
                raise LiveTennisAPIError(
                    "Live Tennis API indicou has_more=true sem retornar dados"
                )
            offset += len(data)

        return collected

    def list_upcoming_singles(
        self,
        tour: str,
        *,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """Retorna todas as partidas futuras de simples do tour informado."""

        rows = self._list_paginated(
            "/matches",
            tour=tour,
            page_size=page_size,
            extra_params={"status": "upcoming"},
        )
        for row in rows:
            if row.get("status") != "upcoming":
                raise LiveTennisAPIError(
                    "Live Tennis API retornou partida com status diferente de upcoming"
                )
        return rows

    def list_fixtures_singles(
        self,
        tour: str,
        *,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """Retorna fixtures de simples do tour.

        O endpoint pode conter estados concluídos/cancelados; por isso esta
        função não usa fixture como filtro operacional. Ele serve apenas para
        metadados de agenda que o objeto Match não carrega, especialmente
        `event_date`.
        """

        return self._list_paginated(
            "/fixtures",
            tour=tour,
            page_size=page_size,
        )

    def list_all_upcoming_singles(self) -> dict[str, list[dict[str, Any]]]:
        """Coleta ATP e WTA separadamente para manter o tour explícito."""

        return {
            "ATP": self.list_upcoming_singles("ATP"),
            "WTA": self.list_upcoming_singles("WTA"),
        }
