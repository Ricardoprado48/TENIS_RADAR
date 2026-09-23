"""Chave natural de partida (docs/018_PWA_ARQUITETURA.md secao 4.1).

`match_id` do radar (`FUTURE:{tour}:{seq}`) e efemero -- reindexado a cada
execucao do CSV bruto do dia (risco R1, secao 12). `match_key` e derivado
so de campos de conteudo (nunca de posicao/indice), entao permanece o mesmo
entre execucoes para a mesma partida. Nunca gravado em `data/outputs/` --
so usado como chave de rota/juncao (calculado aqui, em `src/calendar/`,
onde o provider ja precisa dele para `get_match`; reaproveitavel pelo
radar_service no LOTE D sem duplicar a formula).

Reaproveita `normalize_name` de `src/radar/identity.py` (mesma normalizacao
de nome ja usada na resolucao de identidade do radar -- nao duplica logica,
CLAUDE.md Sec.10).
"""

from __future__ import annotations

import re
from datetime import date

from src.radar.identity import normalize_name

_SLUG_INVALID = re.compile(r"[^a-z0-9]+")


def _slugify(raw: str) -> str:
    normalized = normalize_name(raw)
    slug = _SLUG_INVALID.sub("-", normalized).strip("-")
    return slug


def build_match_key(
    *,
    tour: str,
    tournament: str,
    round_: str,
    player_a: str,
    player_b: str,
    match_date: date,
) -> str:
    """`match_key = slugify(f"{tour}:{tournament}:{round}:{player_a_norm}:{player_b_norm}:{match_date}")`
    (docs/018 secao 4.1). `match_date` e a data local do torneio (o mesmo
    dia usado para nomear `agenda_YYYYMMDD.csv`/`partidas_futuras_*.csv`),
    nunca a data UTC/Sao Paulo convertida -- garante que a mesma partida
    produza a mesma chave nas duas fontes (calendario e radar) mesmo quando
    a conversao de fuso empurra o horario para o dia anterior/seguinte."""
    parts = [
        tour,
        tournament,
        round_,
        player_a,
        player_b,
        match_date.isoformat(),
    ]
    return _slugify(":".join(parts))
