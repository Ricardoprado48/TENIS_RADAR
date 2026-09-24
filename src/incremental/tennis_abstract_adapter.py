"""Adapter de normalização e validação para dados do Tennis Abstract (LOTE J).

Transforma as linhas de `matchmx` do Tennis Abstract no schema bruto Sackmann,
valida a integridade estrita dos 9 campos críticos de saque/devolução (rejeitando
partidas incompletas sem preencher com zero nem estimar), deduplica partidas
cruzadas e converte para a tabela normalizada de partidas.
"""

from __future__ import annotations

from typing import Any
import pandas as pd

from src.normalization.matches import transform_raw_matches
from src.normalization.players import load_players
from . import identity_new as ident_new
from . import dedupe as dedup

CRITICAL_STAT_FIELDS = [
    "w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon", "w_SvGms", "w_bpSaved", "w_bpFaced",
    "l_ace", "l_df", "l_svpt", "l_1stIn", "l_1stWon", "l_2ndWon", "l_SvGms", "l_bpSaved", "l_bpFaced",
]


def _safe_int(val: Any) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def match_context_key(tour: str, date: str, tourn: str, player_a: str, player_b: str, score: str) -> str:
    pair = "|".join(sorted([str(player_a).strip(), str(player_b).strip()]))
    return f"{tour.upper()}:{date}:{tourn}:{pair}:{score}"


def parse_ta_match_row(m: dict[str, str], player_name: str, tour: str) -> tuple[dict[str, Any] | None, str]:
    """Converte um dicionário matchhead em uma linha bruta Sackmann.

    Retorna (row_dict, validation_status). Se incompleto, row_dict pode ser None ou vir
    marcado para descarte.
    """
    wl = m.get("wl", "").strip().upper()
    opp = m.get("opp", "").strip()
    score = m.get("score", "").strip()
    date_str = m.get("date", "").strip()
    tourn = m.get("tourn", "").strip()

    if not wl or not opp or not date_str:
        return None, "MISSING_METADATA"

    is_winner = (wl == "W")
    winner_name = player_name if is_winner else opp
    loser_name = opp if is_winner else player_name

    # Mapeamento dos 9 campos críticos (winner e loser)
    # Regra absoluta: se qualquer um dos 9 campos for None ou vazio, rejeitar.
    raw_stats = {
        # Winner
        "w_ace": _safe_int(m.get("aces" if is_winner else "oaces")),
        "w_df": _safe_int(m.get("dfs" if is_winner else "odfs")),
        "w_svpt": _safe_int(m.get("pts" if is_winner else "opts")),
        "w_1stIn": _safe_int(m.get("firsts" if is_winner else "ofirsts")),
        "w_1stWon": _safe_int(m.get("fwon" if is_winner else "ofwon")),
        "w_2ndWon": _safe_int(m.get("swon" if is_winner else "oswon")),
        "w_SvGms": _safe_int(m.get("games" if is_winner else "ogames")),
        "w_bpSaved": _safe_int(m.get("saved" if is_winner else "osaved")),
        "w_bpFaced": _safe_int(m.get("chances" if is_winner else "ochances")),
        # Loser
        "l_ace": _safe_int(m.get("oaces" if is_winner else "aces")),
        "l_df": _safe_int(m.get("odfs" if is_winner else "dfs")),
        "l_svpt": _safe_int(m.get("opts" if is_winner else "pts")),
        "l_1stIn": _safe_int(m.get("ofirsts" if is_winner else "firsts")),
        "l_1stWon": _safe_int(m.get("ofwon" if is_winner else "fwon")),
        "l_2ndWon": _safe_int(m.get("oswon" if is_winner else "swon")),
        "l_SvGms": _safe_int(m.get("ogames" if is_winner else "games")),
        "l_bpSaved": _safe_int(m.get("osaved" if is_winner else "saved")),
        "l_bpFaced": _safe_int(m.get("ochances" if is_winner else "chances")),
    }

    # Validação dos 9 campos
    missing_fields = [k for k, v in raw_stats.items() if v is None]
    if missing_fields:
        return None, f"INCOMPLETE_STATS:{','.join(missing_fields)}"

    # Parse de matchid (ex: 2026-560-223)
    matchid = m.get("matchid", "")
    tourney_id = ""
    match_num = _safe_int(m.get("matchnum")) or 1
    if matchid:
        parts = matchid.split("-")
        if len(parts) >= 3:
            tourney_id = f"{parts[0]}-{parts[1]}"
            match_num = _safe_int(parts[2]) or match_num
        else:
            tourney_id = matchid
    else:
        tourney_id = f"{date_str[:4]}-TA"

    try:
        tourney_date = int(date_str)
    except ValueError:
        return None, "INVALID_DATE"

    row = {
        "tour": tour.upper(),
        "tourney_id": tourney_id,
        "tourney_name": tourn,
        "surface": m.get("surf", "Hard"),
        "tourney_level": m.get("level", "A"),
        "tourney_date": tourney_date,
        "match_num": match_num,
        "round": m.get("round", "R32"),
        "best_of": 3,
        "minutes": _safe_int(m.get("time")),
        "score": score,
        "winner_name": winner_name,
        "winner_hand": m.get("ohand", "R") if not is_winner else "R",
        "winner_rank": _safe_int(m.get("rank" if is_winner else "orank")),
        "winner_rank_points": None,
        "loser_name": loser_name,
        "loser_hand": m.get("ohand", "R") if is_winner else "R",
        "loser_rank": _safe_int(m.get("orank" if is_winner else "rank")),
        "loser_rank_points": None,
        **raw_stats,
    }

    return row, "VALID"


def process_tennis_abstract_matches(
    raw_payloads: list[dict[str, Any]],
    tour: str,
    cutoff_date: str = "2026-05-25",
    players_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Recebe payloads de jogadores do Tennis Abstract, filtra pós-cutoff,

    valida os 9 campos, deduplica e normaliza no schema Sackmann.
    """
    tour_clean = tour.upper()
    cutoff_int = int(cutoff_date.replace("-", ""))

    valid_rows: list[dict[str, Any]] = []
    seen_context_keys: set[str] = set()
    rejected_reasons: dict[str, int] = {}
    post_cutoff_count = 0
    pre_cutoff_count = 0

    for payload in raw_payloads:
        p_info = payload.get("player", {})
        p_name = p_info.get("name", "")
        p_tour = p_info.get("tour", tour_clean).upper()
        if p_tour != tour_clean:
            continue

        for m in payload.get("matches", []):
            dt_str = m.get("date", "")
            try:
                dt_int = int(dt_str)
            except (ValueError, TypeError):
                continue

            if dt_int <= cutoff_int:
                pre_cutoff_count += 1
                continue

            post_cutoff_count += 1
            row, status = parse_ta_match_row(m, p_name, tour_clean)
            if status != "VALID" or row is None:
                rejected_reasons[status] = rejected_reasons.get(status, 0) + 1
                continue

            ctx_key = match_context_key(
                tour=tour_clean,
                date=str(row["tourney_date"]),
                tourn=row["tourney_name"],
                player_a=row["winner_name"],
                player_b=row["loser_name"],
                score=row["score"],
            )
            if ctx_key in seen_context_keys:
                rejected_reasons["DUPLICATE_CROSS_PLAYER"] = (
                    rejected_reasons.get("DUPLICATE_CROSS_PLAYER", 0) + 1
                )
                continue
            seen_context_keys.add(ctx_key)

            valid_rows.append(row)

    if not valid_rows:
        return {
            "raw_df": pd.DataFrame(),
            "transformed_df": pd.DataFrame(),
            "total_post_cutoff": post_cutoff_count,
            "valid_count": 0,
            "rejected_count": sum(rejected_reasons.values()),
            "rejected_reasons": rejected_reasons,
        }

    raw_df = pd.DataFrame(valid_rows)

    if players_df is None:
        players_df, _ = load_players(tour_clean.lower())

    # Resolver identidade de jogadores
    resolved_df = ident_new.resolve_incremental_players(raw_df, tour_clean, players_df)

    # Normalizar usando transform_raw_matches (gera as 2 perspectivas por partida)
    transform_result = transform_raw_matches(resolved_df, tour_clean)
    transformed_df = transform_result["table"]

    return {
        "raw_df": resolved_df,
        "transformed_df": transformed_df,
        "total_post_cutoff": post_cutoff_count,
        "valid_count": len(valid_rows),
        "rejected_count": sum(rejected_reasons.values()),
        "rejected_reasons": rejected_reasons,
    }

