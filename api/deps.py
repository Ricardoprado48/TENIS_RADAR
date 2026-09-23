"""Dependencias FastAPI compartilhadas entre rotas.

Nesta fase (LOTE A) so existe a dependencia de configuracao. Dependencias de
acesso a dados (paths de data/, providers) entram junto dos lotes que
realmente as usam (C em diante), para nao criar abstracao sem uso
(CLAUDE.md Sec.20).
"""

from __future__ import annotations

from functools import lru_cache

from api.config import Settings, get_settings as _get_settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _get_settings()
