"""Jogadores unicos da agenda real (LOTE J, T3).

Le `data/outputs/phase8/partidas_resolvidas.parquet` (saida da Fase 8 base)
e produz 1 linha por jogador, deduplicada por `player_id` -- nunca por nome.
Nome canonico, mao e data de nascimento vem de
`data/processed/{tour}/players.parquet`; `sackmann_last` e a ultima
`tournament_date` do jogador na base Sackmann congelada. Tudo somente leitura.

Lados sem `player_id` (unresolved) nao podem ser deduplicados por identidade:
cada ocorrencia vira uma linha propria, com `player_id` nulo e o nome bruto
da agenda. `fuzzy_review` nunca e tratado como confiavel (`trusted=False`).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.normalization.config import PROCESSED_DIRS

from . import config as cfg

RESOLVED_PATH = cfg.PHASE8_OUTPUT_DIR / "partidas_resolvidas.parquet"

TRUSTED_METHODS = ("exact", "alias")
# do menos para o mais confiavel: um jogador visto com metodos diferentes
# fica com o menos confiavel (conservador)
_METHOD_RANK = {"unresolved": 0, "fuzzy_review": 1, "alias": 2, "exact": 3}

AGENDA_PLAYER_COLUMNS = [
    "player_id", "player_name", "tour", "hand", "dob", "resolution_method",
    "resolution_methods", "trusted", "raw_names", "n_agenda_matches", "sackmann_last",
]


def _agenda_sides(resolved: pd.DataFrame) -> pd.DataFrame:
    sides = []
    for side in ("a", "b"):
        part = resolved[["tour", "raw_match_seq", f"player_id_{side}",
                         f"player_{side}_raw", f"resolution_method_{side}"]].copy()
        part.columns = ["tour", "raw_match_seq", "player_id", "raw_name", "resolution_method"]
        part["side"] = side.upper()
        sides.append(part)
    return pd.concat(sides, ignore_index=True)


def _players_for(tour: str, players_by_tour: dict[str, pd.DataFrame] | None) -> pd.DataFrame:
    if players_by_tour is not None and tour in players_by_tour:
        return players_by_tour[tour]
    return pd.read_parquet(PROCESSED_DIRS[tour.lower()] / "players.parquet")


def _sackmann_last_for(tour: str, sackmann_last_by_tour: dict[str, pd.Series] | None) -> pd.Series:
    if sackmann_last_by_tour is not None and tour in sackmann_last_by_tour:
        return sackmann_last_by_tour[tour]
    base = pd.read_parquet(
        PROCESSED_DIRS[tour.lower()] / "matches.parquet", columns=["player_id", "tournament_date"],
    )
    return base.groupby("player_id")["tournament_date"].max()


def extract_agenda_players(
    resolved: pd.DataFrame,
    players_by_tour: dict[str, pd.DataFrame] | None = None,
    sackmann_last_by_tour: dict[str, pd.Series] | None = None,
) -> pd.DataFrame:
    """`resolved`: `partidas_resolvidas` da Fase 8 (todas as linhas, inclusive
    nao utilizaveis -- a agenda e o que foi coletado). Retorna DataFrame com
    `AGENDA_PLAYER_COLUMNS`, ordenado por (tour, player_id, raw_names)."""

    sides = _agenda_sides(resolved)
    rows = []

    identified = sides[sides["player_id"].notna()]
    for (tour, player_id), grp in identified.groupby(["tour", "player_id"], sort=True):
        methods = sorted(set(grp["resolution_method"]), key=lambda m: _METHOD_RANK.get(m, -1))
        rows.append({
            "tour": tour, "player_id": player_id,
            "resolution_method": methods[0],
            "resolution_methods": "|".join(methods),
            "raw_names": "|".join(sorted(set(grp["raw_name"]))),
            "n_agenda_matches": int(grp["raw_match_seq"].nunique()),
        })

    for r in sides[sides["player_id"].isna()].itertuples(index=False):
        rows.append({
            "tour": r.tour, "player_id": None,
            "resolution_method": r.resolution_method,
            "resolution_methods": r.resolution_method,
            "raw_names": r.raw_name,
            "n_agenda_matches": 1,
        })

    out = pd.DataFrame(rows, columns=["tour", "player_id", "resolution_method",
                                      "resolution_methods", "raw_names", "n_agenda_matches"])
    out["trusted"] = out["resolution_method"].isin(TRUSTED_METHODS)

    enriched = []
    for tour, grp in out.groupby("tour", sort=True):
        players = _players_for(tour, players_by_tour).set_index("player_id")
        last = _sackmann_last_for(tour, sackmann_last_by_tour)
        grp = grp.copy()
        known = grp["player_id"].isin(players.index)
        grp["player_name"] = grp["player_id"].map(players["name"]).where(known, grp["raw_names"])
        grp["hand"] = grp["player_id"].map(players["hand"])
        grp["dob"] = grp["player_id"].map(players["dob"])
        grp["sackmann_last"] = grp["player_id"].map(last)
        enriched.append(grp)

    if not enriched:
        return pd.DataFrame(columns=AGENDA_PLAYER_COLUMNS)
    result = pd.concat(enriched, ignore_index=True)[AGENDA_PLAYER_COLUMNS]
    return result.sort_values(["tour", "player_id", "raw_names"], na_position="last").reset_index(drop=True)


def load_agenda_players(resolved_path: Path | None = None) -> pd.DataFrame:
    """Jogadores unicos da agenda a partir de `partidas_resolvidas.parquet`."""
    return extract_agenda_players(pd.read_parquet(resolved_path or RESOLVED_PATH))
