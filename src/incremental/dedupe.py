"""Deduplicacao contra a base historica existente (item 4 da instrucao).

Nunca sobrescreve uma partida historica silenciosamente: toda partida
incremental e comparada com `data/processed/{tour}/matches.parquet` por
`match_id` estavel (tourney_id + match_num, igual a Fase 2) e, como reforco
(caso o match_num nao seja estavel entre fontes), por
(data, torneio, dupla de jogadores, placar)."""

from __future__ import annotations

import pandas as pd


def detect_duplicates(raw_incremental: pd.DataFrame, existing_matches: pd.DataFrame, tour: str) -> pd.DataFrame:
    """`raw_incremental`: linhas cruas com tourney_id/match_num/tourney_date
    (formato YYYYMMDD)/tourney_name/winner_name/loser_name/score. `existing_matches`:
    `data/processed/{tour}/matches.parquet` (1 linha por jogador por
    partida -- usa so `result == "W"` para comparar 1x por partida).

    Retorna `raw_incremental` + `is_duplicate_match_id`, `is_duplicate_context`,
    `is_duplicate` (OR das duas) e `duplicate_reason`."""

    out = raw_incremental.copy()
    out["match_id"] = tour.upper() + ":" + out["tourney_id"].astype(str) + ":" + out["match_num"].astype(str)

    existing_winners = existing_matches[existing_matches["result"] == "W"].copy()

    existing_ids = set(existing_winners["match_id"])
    out["is_duplicate_match_id"] = out["match_id"].isin(existing_ids)

    def _pair_key(a, b) -> str:
        return "|".join(sorted([str(a), str(b)]))

    existing_context_keys = set(
        existing_winners["tournament_date"].astype(str)
        + "|" + existing_winners["tournament"].astype(str)
        + "|" + [
            _pair_key(a, b) for a, b in zip(existing_winners["player_name"], existing_winners["opponent_name"])
        ]
        + "|" + existing_winners["score"].astype(str)
    )

    incremental_dates = pd.to_datetime(out["tourney_date"], format="%Y%m%d", errors="coerce").astype(str)
    incremental_pairs = [_pair_key(a, b) for a, b in zip(out["winner_name"], out["loser_name"])]
    incremental_context_keys = (
        incremental_dates + "|" + out["tourney_name"].astype(str) + "|" + incremental_pairs + "|" + out["score"].astype(str)
    )
    out["is_duplicate_context"] = incremental_context_keys.isin(existing_context_keys)

    out["is_duplicate"] = out["is_duplicate_match_id"] | out["is_duplicate_context"]
    out["duplicate_reason"] = [
        "match_id" if a else ("torneio+data+jogadores+placar" if b else "")
        for a, b in zip(out["is_duplicate_match_id"], out["is_duplicate_context"])
    ]
    return out
