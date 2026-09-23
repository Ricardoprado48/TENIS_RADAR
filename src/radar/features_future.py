"""Features pre-jogo para partidas futuras (item 3 da instrucao).

Reaproveita EXATAMENTE o motor point-in-time da Fase 3
(`src.features.profile.build_player_profile` /
`src.features.matchup.build_matchup_table`) em vez de reimplementa-lo: cada
partida futura vira duas linhas SINTETICAS (uma por jogador, com o
adversario cruzado -- Serve A x Return B e Serve B x Return A, CLAUDE.md
#2), no MESMO schema da tabela de partidas da Fase 2, anexadas ao final da
tabela historica real do tour (ordenadas por data, entao sempre depois de
qualquer partida real). Como as janelas historicas da Fase 3 usam
estritamente `shift(1)`/soma-ate-a-linha-anterior por jogador (nunca a
propria linha), as duas linhas sinteticas:

  1) recebem, em suas colunas player_serve_*/player_return_*, EXATAMENTE o
     estado point-in-time de cada jogador construido so a partir de partidas
     REAIS anteriores -- nenhuma informacao da propria partida futura
     (que nem existe ainda) entra nessas colunas;
  2) nunca contaminam a janela de nenhuma outra linha, real ou sintetica,
     porque todas as suas proprias colunas de estatistica bruta (aces,
     double_faults, ...) sao deixadas `<NA>` (nunca inventadas) e elas sao
     descartadas logo depois de extraidas -- nunca gravadas de volta em
     data/processed/.

Isso e o mesmo truque descrito em docs/013 secao 2: reusar o motor testado
da Fase 3 em vez de duplicar a logica de shift(1)/janela.
"""

from __future__ import annotations

import pandas as pd

from src.features.matchup import build_matchup_table
from src.features.profile import build_player_profile
from src.normalization.config import PROCESSED_DIRS
from src.normalization.matches import INT_COLUMNS, OUTPUT_COLUMNS

_STRING_COLUMNS = [
    "match_id", "tour", "tournament", "tourney_id", "round", "surface",
    "tourney_level", "score", "player_id", "opponent_id", "player_name",
    "opponent_name", "player_hand", "opponent_hand", "result",
]


def load_historical_matches(tour: str, override_path=None) -> pd.DataFrame:
    """`override_path` (opcional) aponta para uma base historica alternativa
    -- usado pela Fase 8.1 para rodar o radar contra a base incremental sem
    tocar em `data/processed/{tour}/matches.parquet` (Fase 2). Quando
    omitido, comportamento identico ao da Fase 8."""

    path = override_path or (PROCESSED_DIRS[tour.lower()] / "matches.parquet")
    df = pd.read_parquet(path)
    return df.sort_values(
        ["tournament_date", "tourney_id", "match_id", "result"],
        ascending=[True, True, True, False],
    ).reset_index(drop=True)


def _synthetic_match_id(tour: str, raw_match_seq: int) -> str:
    return f"FUTURE:{tour}:{raw_match_seq}"


def build_synthetic_rows(resolved_tour: pd.DataFrame) -> pd.DataFrame:
    """Uma partida usavel (`usable_for_prediction`) vira 2 linhas, no schema
    de `src.normalization.matches.OUTPUT_COLUMNS`. Todas as estatisticas da
    propria partida ficam `<NA>` -- nunca inventadas (CLAUDE.md #23)."""

    rows: list[dict] = []
    for r in resolved_tour.itertuples(index=False):
        match_id = _synthetic_match_id(r.tour, r.raw_match_seq)
        tourney_id = f"FUTURE-{pd.Timestamp(r.match_date).date()}"
        base = {
            "match_id": match_id, "tour": r.tour, "tournament": r.tournament,
            "tourney_id": tourney_id, "tournament_date": r.match_date, "round": r.round,
            "surface": r.surface, "tourney_level": pd.NA, "best_of": pd.NA,
            "minutes": pd.NA, "score": pd.NA,
        }
        sides = [
            (r.player_id_a, r.player_id_b, r.resolved_name_a or r.player_a_raw, r.resolved_name_b or r.player_b_raw),
            (r.player_id_b, r.player_id_a, r.resolved_name_b or r.player_b_raw, r.resolved_name_a or r.player_a_raw),
        ]
        for own_id, opp_id, own_name, opp_name in sides:
            row = dict(base)
            row["player_id"] = own_id
            row["opponent_id"] = opp_id
            row["player_name"] = own_name
            row["opponent_name"] = opp_name
            row["player_hand"] = pd.NA
            row["opponent_hand"] = pd.NA
            row["player_rank"] = pd.NA
            row["opponent_rank"] = pd.NA
            row["player_rank_points"] = pd.NA
            row["opponent_rank_points"] = pd.NA
            row["result"] = pd.NA
            for stat_col in INT_COLUMNS:
                if stat_col not in row:
                    row[stat_col] = pd.NA
            rows.append(row)

    out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    for col in INT_COLUMNS:
        out[col] = pd.array(pd.to_numeric(out[col], errors="coerce"), dtype="Int64")
    for col in _STRING_COLUMNS:
        out[col] = out[col].astype("string")
    out["tournament_date"] = pd.to_datetime(out["tournament_date"])
    return out[OUTPUT_COLUMNS]


def build_future_feature_rows(tour: str, resolved_tour: pd.DataFrame, override_path=None) -> pd.DataFrame:
    """Retorna a tabela de features (perfil + matchup, mesmo schema da
    Fase 3) SO das linhas sinteticas de partidas futuras usaveis desse
    tour. `override_path`: ver `load_historical_matches`."""

    usable = resolved_tour[resolved_tour["usable_for_prediction"] & ~resolved_tour.get(
        "is_duplicate", pd.Series(False, index=resolved_tour.index))]
    if usable.empty:
        return pd.DataFrame()

    historical = load_historical_matches(tour, override_path)
    synthetic = build_synthetic_rows(usable)

    augmented = pd.concat([historical, synthetic], ignore_index=True)
    augmented = augmented.sort_values(
        ["tournament_date", "tourney_id", "match_id", "result"],
        ascending=[True, True, True, False],
    ).reset_index(drop=True)

    profile = build_player_profile(augmented)
    full = build_matchup_table(profile)

    future_mask = full["match_id"].str.startswith("FUTURE:")
    return full.loc[future_mask].reset_index(drop=True)
