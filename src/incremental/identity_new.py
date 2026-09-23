"""Resolucao de identidade para jogadores em partidas incrementais (item 5
da instrucao: "Resolver novos jogadores de forma explicita").

Reaproveita o mesmo resolvedor de 4 niveis da Fase 8
(`src.radar.identity.PlayerIndex`: exact / alias / fuzzy_review /
unresolved) em vez de duplicar logica de casamento de nomes. Um jogador que
nao resolve contra a base existente recebe um id sintetico, claramente
marcado como novo (`NEW-<nome-normalizado>`) -- nunca reaproveita
silenciosamente o id de um jogador existente (mesma regra da Fase 8, item 2:
nunca associar por acaso quando houver duvida)."""

from __future__ import annotations

import pandas as pd

from src.radar.identity import PlayerIndex, normalize_name

from . import config as cfg


def mint_new_player_id_raw(name: str) -> str:
    slug = normalize_name(name).replace(" ", "-").upper()
    return f"{cfg.NEW_PLAYER_ID_PREFIX}-{slug}" if slug else f"{cfg.NEW_PLAYER_ID_PREFIX}-UNKNOWN"


def resolve_incremental_players(raw_df: pd.DataFrame, tour: str, players: pd.DataFrame) -> pd.DataFrame:
    """`raw_df`: linhas cruas no schema Sackmann com winner_name/loser_name
    ja preenchidos e winner_id/loser_id AINDA AUSENTES. Retorna copia com
    winner_id/loser_id preenchidos (formato "raw", sem prefixo de tour --
    o mesmo que `canonical_player_id` espera receber) e colunas
    winner_resolution_method / loser_resolution_method / *_resolution_note.
    Um jogador ja existente (exact/alias/fuzzy_review) usa o
    `player_id_raw` real; um jogador sem candidato (unresolved) recebe um
    id sintetico via `mint_new_player_id_raw`."""

    index = PlayerIndex(players)
    out = raw_df.copy()
    for role in ("winner", "loser"):
        name_col = f"{role}_name"
        results = out[name_col].map(index.resolve)
        out[f"{role}_id"] = [
            r.player_id.split("-", 1)[1] if r.method != "unresolved" else mint_new_player_id_raw(name)
            for r, name in zip(results, out[name_col])
        ]
        out[f"{role}_resolution_method"] = [r.method for r in results]
        out[f"{role}_resolution_note"] = [r.note for r in results]
    return out
