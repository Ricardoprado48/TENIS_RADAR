"""Resolucao de identidade para jogadores em partidas incrementais (item 5
da instrucao: "Resolver novos jogadores de forma explicita").

Reaproveita o mesmo resolvedor de 4 niveis da Fase 8
(`src.radar.identity.PlayerIndex`: exact / alias / fuzzy_review /
unresolved) em vez de duplicar logica de casamento de nomes. Um jogador que
nao resolve contra a base existente recebe um id sintetico, claramente
marcado como novo (`NEW-<nome-normalizado>`) -- nunca reaproveita
silenciosamente o id de um jogador existente (mesma regra da Fase 8, item 2:
nunca associar por acaso quando houver duvida).

Somente `exact` e `alias` sao identidade confiavel (doc 027 §6).
`fuzzy_review` e tratado como nao resolvido: recebe id sintetico `NEW-`,
e o metodo original fica registrado para revisao manual."""

from __future__ import annotations

import pandas as pd

from src.radar.identity import PlayerIndex, normalize_name

from . import config as cfg


def mint_new_player_id_raw(name: str) -> str:
    slug = normalize_name(name).replace(" ", "-").upper()
    return f"{cfg.NEW_PLAYER_ID_PREFIX}-{slug}" if slug else f"{cfg.NEW_PLAYER_ID_PREFIX}-UNKNOWN"


TRUSTED_METHODS = ("exact", "alias")


def resolve_player_names(names: pd.Series, players: pd.DataFrame) -> pd.DataFrame:
    """Resolve cada nome contra `players`. Retorna DataFrame (mesmo indice)
    com `id_raw` (formato "raw", sem prefixo de tour), `method` e `note`.
    So `exact`/`alias` reaproveitam o id real; `fuzzy_review` e
    `unresolved` recebem id sintetico `NEW-`."""

    index = PlayerIndex(players)
    results = names.map(index.resolve)
    return pd.DataFrame({
        "id_raw": [
            r.player_id.split("-", 1)[1] if r.method in TRUSTED_METHODS else mint_new_player_id_raw(name)
            for r, name in zip(results, names)
        ],
        "method": [r.method for r in results],
        "note": [r.note for r in results],
    }, index=names.index)


def resolve_incremental_players(raw_df: pd.DataFrame, tour: str, players: pd.DataFrame) -> pd.DataFrame:
    """`raw_df`: linhas cruas no schema Sackmann com winner_name/loser_name
    ja preenchidos e winner_id/loser_id AINDA AUSENTES. Retorna copia com
    winner_id/loser_id preenchidos (formato "raw", sem prefixo de tour --
    o mesmo que `canonical_player_id` espera receber) e colunas
    winner_resolution_method / loser_resolution_method / *_resolution_note.
    Um jogador resolvido por exact/alias usa o `player_id_raw` real; um
    jogador fuzzy_review ou unresolved recebe um id sintetico via
    `mint_new_player_id_raw`."""

    out = raw_df.copy()
    for role in ("winner", "loser"):
        res = resolve_player_names(out[f"{role}_name"], players)
        out[f"{role}_id"] = res["id_raw"]
        out[f"{role}_resolution_method"] = res["method"]
        out[f"{role}_resolution_note"] = res["note"]
    return out
