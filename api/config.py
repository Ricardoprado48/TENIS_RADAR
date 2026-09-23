"""Configuracao basica da API, por variavel de ambiente com defaults locais.

Nao usa pydantic-settings (dependencia nova evitada de proposito, CLAUDE.md
Sec.20) -- um leitor simples de os.environ e suficiente para os campos de
hoje.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _split_origins(raw: str) -> list[str]:
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str = "Tennis Radar"
    api_version: str = "0.1.0"
    # timezone padrao da PWA (docs/018 secao 4.2) -- nao e o fuso do
    # torneio, e o fuso de exibicao/operacao do usuario.
    default_timezone: str = "America/Sao_Paulo"
    host: str = "127.0.0.1"
    port: int = 8000
    # apenas os hosts locais do Vite (docs/018 LOTE A/B) -- nunca "*".
    allowed_origins: list[str] = field(
        default_factory=lambda: _split_origins(
            os.getenv(
                "TENNIS_RADAR_API_ALLOWED_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            )
        )
    )


def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("TENNIS_RADAR_API_APP_NAME", "Tennis Radar"),
        api_version=os.getenv("TENNIS_RADAR_API_VERSION", "0.1.0"),
        default_timezone=os.getenv("TENNIS_RADAR_API_TIMEZONE", "America/Sao_Paulo"),
        host=os.getenv("TENNIS_RADAR_API_HOST", "127.0.0.1"),
        port=int(os.getenv("TENNIS_RADAR_API_PORT", "8000")),
    )
