"""Adapter de normalização e validação para dados do Tennis Abstract (LOTE J).

Transforma as linhas de `matchmx` do Tennis Abstract no schema bruto Sackmann,
valida a integridade estrita dos 9 campos críticos de saque/devolução (rejeitando
partidas incompletas sem preencher com zero nem estimar), deduplica partidas
cruzadas e converte para a tabela normalizada de partidas.

Regras comprovadas no preflight T1 (876 partidas TA × Sackmann, 100% iguais):
- `tourney_level` = `level` do TA; `best_of` = `max` do TA; `round` = `round` do TA;
- `match_id` = `matchid` do TA cortado no ÚLTIMO hífen (necessário p/ Copa Davis).
Nenhum campo recebe default inventado: ausente => rejeitado (ou NA, quando o
campo também é opcional no Sackmann, como `minutes` e `rank`).

O jogador coletado chega com `player_id` conhecido (`payload["player"]["player_id"]`)
e nunca é re-resolvido por nome; só o adversário é resolvido (exact/alias).
Gate de identidade (T4): só entram partidas de payloads cuja verificação
(`payload["identity"]`, ver `ta_identity`) é VERIFIED para esse mesmo player_id.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.normalization.config import PROCESSED_DIRS
from src.normalization.matches import transform_raw_matches
from src.normalization.players import load_players
from . import identity_new as ident_new

CRITICAL_STAT_FIELDS = [
    "w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon", "w_SvGms", "w_bpSaved", "w_bpFaced",
    "l_ace", "l_df", "l_svpt", "l_1stIn", "l_1stWon", "l_2ndWon", "l_SvGms", "l_bpSaved", "l_bpFaced",
]

VALID_BEST_OF = (3, 5)
COLLECTED_METHOD = "collected_player_id"
IDENTITY_VERIFIED = "VERIFIED"  # = ta_identity.VERIFIED (sem import: evita ciclo)


@dataclass(frozen=True)
class CollectedPlayer:
    """Jogador cuja página TA foi coletada. `player_id` canônico (ex.: "ATP-207989")."""
    player_id: str
    name: str
    hand: str | None


@dataclass(frozen=True)
class AcceptancePolicy:
    """Níveis e rodadas aceitos: só os que já existem na base Sackmann do tour
    (decisão B1). Rodadas de qualifying (Q1-Q3) não existem na base e ficam fora."""
    levels: frozenset[str]
    rounds: frozenset[str]


def policy_from_base(base: pd.DataFrame) -> AcceptancePolicy:
    return AcceptancePolicy(
        levels=frozenset(base["tourney_level"].dropna().astype(str)),
        rounds=frozenset(base["round"].dropna().astype(str)),
    )


def load_acceptance_policy(tour: str) -> AcceptancePolicy:
    """Lê (somente leitura) níveis e rodadas presentes na base Sackmann do tour."""
    base = pd.read_parquet(
        PROCESSED_DIRS[tour.lower()] / "matches.parquet", columns=["tourney_level", "round"],
    )
    return policy_from_base(base)


def _safe_int(val: Any) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _clean(val: Any) -> str | None:
    s = str(val).strip() if val is not None else ""
    return s or None


def parse_matchid(matchid: str) -> tuple[str, int] | None:
    """`2026-520-223` -> ("2026-520", 223);
    `2024-M-DC-2024-FLS-M-NED-ESP-01-002` -> ("2024-M-DC-2024-FLS-M-NED-ESP-01", 2).
    Retorna None se não houver hífen, prefixo vazio ou último bloco não numérico."""
    matchid = (matchid or "").strip()
    if "-" not in matchid:
        return None
    tourney_id, num = matchid.rsplit("-", 1)
    if not tourney_id or not num.isdigit():
        return None
    return tourney_id, int(num)


def parse_ta_match_row(
    m: dict[str, str],
    player: CollectedPlayer,
    tour: str,
    policy: AcceptancePolicy,
) -> tuple[dict[str, Any] | None, str]:
    """Converte um dicionário matchhead em uma linha bruta Sackmann.

    Retorna (row_dict, "VALID") ou (None, motivo_da_rejeição). O lado do
    jogador coletado já vem com id; o lado do adversário fica com id None
    (resolvido depois, em lote)."""
    wl = (m.get("wl") or "").strip().upper()
    opp = _clean(m.get("opp"))
    date_str = _clean(m.get("date"))
    if wl not in ("W", "L") or not opp or not date_str:
        return None, "MISSING_METADATA"

    if not _clean(m.get("matchid")):
        return None, "MISSING_MATCHID"
    parsed_id = parse_matchid(m["matchid"])
    if parsed_id is None:
        return None, "INVALID_MATCHID"
    tourney_id, match_num = parsed_id

    tourney_date = _safe_int(date_str)
    if tourney_date is None or len(date_str) != 8:
        return None, "INVALID_DATE"

    level = _clean(m.get("level"))
    if level is None:
        return None, "MISSING_LEVEL"
    if level not in policy.levels:
        return None, f"LEVEL_OUT_OF_POLICY:{level}"

    rnd = _clean(m.get("round"))
    if rnd is None:
        return None, "MISSING_ROUND"
    if rnd not in policy.rounds:
        return None, f"ROUND_OUT_OF_POLICY:{rnd}"

    best_of = _safe_int(m.get("max"))
    if best_of not in VALID_BEST_OF:
        return None, "INVALID_BEST_OF"

    surface = _clean(m.get("surf"))
    if surface is None:
        return None, "MISSING_SURFACE"

    score = _clean(m.get("score"))
    if score is None:
        return None, "MISSING_SCORE"

    is_winner = wl == "W"
    own, opp_side = ("winner", "loser") if is_winner else ("loser", "winner")

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

    missing_fields = [k for k, v in raw_stats.items() if v is None]
    if missing_fields:
        return None, f"INCOMPLETE_STATS:{','.join(missing_fields)}"

    row = {
        "tour": tour.upper(),
        "tourney_id": tourney_id,
        "tourney_name": _clean(m.get("tourn")),
        "surface": surface,
        "tourney_level": level,
        "tourney_date": tourney_date,
        "match_num": match_num,
        "round": rnd,
        "best_of": best_of,
        "minutes": _safe_int(m.get("time")),
        "score": score,
        f"{own}_id": player.player_id.split("-", 1)[1],
        f"{own}_name": player.name,
        f"{own}_hand": player.hand,
        f"{own}_rank": _safe_int(m.get("rank")),
        f"{own}_rank_points": None,
        f"{own}_resolution_method": COLLECTED_METHOD,
        f"{opp_side}_id": None,
        f"{opp_side}_name": opp,
        f"{opp_side}_hand": _clean(m.get("ohand")),
        f"{opp_side}_rank": _safe_int(m.get("orank")),
        f"{opp_side}_rank_points": None,
        f"{opp_side}_resolution_method": None,
        "_opp_side": opp_side,
        **raw_stats,
    }
    return row, "VALID"


def _match_signature(row: dict[str, Any]) -> tuple:
    return (row["score"], *(row[c] for c in CRITICAL_STAT_FIELDS))


def _collected_player(p_info: dict, players_idx: pd.DataFrame) -> CollectedPlayer | None:
    pid = p_info.get("player_id")
    if not pid or pid not in players_idx.index:
        return None
    rec = players_idx.loc[pid]
    hand = rec["hand"]
    return CollectedPlayer(player_id=pid, name=str(rec["name"]), hand=None if pd.isna(hand) else str(hand))


def _identity_block_reason(payload: dict, p_info: dict) -> str | None:
    """None se a identidade da página foi VERIFIED para o player_id do payload;
    senão o motivo de rejeição `IDENTITY_NOT_VERIFIED:<status>`."""
    identity = payload.get("identity") or {}
    status = identity.get("identity_status")
    if status == IDENTITY_VERIFIED and identity.get("player_id") == p_info.get("player_id"):
        return None
    if status == IDENTITY_VERIFIED:
        return "IDENTITY_NOT_VERIFIED:PLAYER_ID_MISMATCH"
    return f"IDENTITY_NOT_VERIFIED:{status or 'MISSING'}"


def _resolve_opponents(raw_df: pd.DataFrame, players_df: pd.DataFrame) -> pd.DataFrame:
    """Preenche o lado do adversário ainda sem id: exact/alias usam o id e a mão
    da base; fuzzy_review/unresolved recebem id `NEW-` (identity_new) e ficam
    com a mão informada pelo TA (ou NA)."""
    out = raw_df.copy()
    hand_by_raw = players_df.drop_duplicates("player_id_raw").set_index("player_id_raw")["hand"]
    for side in ("winner", "loser"):
        pending = (out["_opp_side"] == side) & out[f"{side}_id"].isna()
        if not pending.any():
            continue
        res = ident_new.resolve_player_names(out.loc[pending, f"{side}_name"], players_df)
        out.loc[pending, f"{side}_id"] = res["id_raw"]
        out.loc[pending, f"{side}_resolution_method"] = res["method"]
        trusted = res["method"].isin(ident_new.TRUSTED_METHODS)
        base_hand = res["id_raw"].map(hand_by_raw)
        use_base = trusted & base_hand.notna()
        out.loc[use_base[use_base].index, f"{side}_hand"] = base_hand[use_base]
    return out.drop(columns=["_opp_side"])


def process_tennis_abstract_matches(
    raw_payloads: list[dict[str, Any]],
    tour: str,
    cutoff_date: str = "2026-05-25",
    players_df: pd.DataFrame | None = None,
    policy: AcceptancePolicy | None = None,
) -> dict[str, Any]:
    """Recebe payloads de jogadores do Tennis Abstract (cada um com
    `player.player_id` e `identity` VERIFIED), filtra pós-cutoff, valida,
    deduplica por `match_id` e normaliza no schema Sackmann.

    Retorna também `per_player`: {player_id: {n_post_cutoff, n_valid,
    n_duplicate, rejected_reasons}} para a freshness por jogador (T7)."""
    tour_clean = tour.upper()
    cutoff_int = int(cutoff_date.replace("-", ""))

    if players_df is None:
        players_df, _ = load_players(tour_clean.lower())
    if policy is None:
        policy = load_acceptance_policy(tour_clean)
    players_idx = players_df.drop_duplicates("player_id").set_index("player_id")

    rows_by_match: dict[str, dict[str, Any]] = {}
    rejected_reasons: dict[str, int] = {}
    per_player: dict[str, dict[str, Any]] = {}
    post_cutoff_count = 0

    def _reject(stats: dict, reason: str) -> None:
        rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1
        stats["rejected_reasons"][reason] = stats["rejected_reasons"].get(reason, 0) + 1

    for payload in raw_payloads:
        p_info = payload.get("player", {})
        if p_info.get("tour", tour_clean).upper() != tour_clean:
            continue
        key = p_info.get("player_id") or f"UNKNOWN:{p_info.get('name', '')}"
        stats = per_player.setdefault(
            key, {"n_post_cutoff": 0, "n_valid": 0, "n_duplicate": 0, "rejected_reasons": {}},
        )
        player = _collected_player(p_info, players_idx)
        identity_block = _identity_block_reason(payload, p_info)

        for m in payload.get("matches", []):
            dt_int = _safe_int(m.get("date"))
            if dt_int is None or dt_int <= cutoff_int:
                continue

            post_cutoff_count += 1
            stats["n_post_cutoff"] += 1
            if player is None:
                _reject(stats, "UNKNOWN_PLAYER_ID")
                continue
            if identity_block is not None:
                _reject(stats, identity_block)
                continue

            row, status = parse_ta_match_row(m, player, tour_clean, policy)
            if status != "VALID" or row is None:
                _reject(stats, status)
                continue

            match_id = f"{tour_clean}:{row['tourney_id']}:{row['match_num']}"
            seen = rows_by_match.get(match_id)
            if seen is not None:
                stats["n_duplicate"] += 1
                _reject(stats, "DUPLICATE_CROSS_PLAYER")
                if _match_signature(seen) != _match_signature(row):
                    _reject(stats, "DUPLICATE_CONFLICT")
                # a mesma partida vista pela página do adversário: o id dele é
                # conhecido, então dispensa a resolução por nome
                opp_side = seen["_opp_side"]
                own_id = player.player_id.split("-", 1)[1]
                if seen[f"{opp_side}_id"] is None and own_id not in (seen["winner_id"], seen["loser_id"]):
                    seen[f"{opp_side}_id"] = own_id
                    seen[f"{opp_side}_name"] = player.name
                    seen[f"{opp_side}_hand"] = player.hand
                    seen[f"{opp_side}_resolution_method"] = COLLECTED_METHOD
                continue

            rows_by_match[match_id] = row
            stats["n_valid"] += 1

    valid_rows = list(rows_by_match.values())
    if not valid_rows:
        return {
            "raw_df": pd.DataFrame(),
            "transformed_df": pd.DataFrame(),
            "total_post_cutoff": post_cutoff_count,
            "valid_count": 0,
            "rejected_count": sum(rejected_reasons.values()),
            "rejected_reasons": rejected_reasons,
            "per_player": per_player,
        }

    raw_df = _resolve_opponents(pd.DataFrame(valid_rows), players_df)

    # Normalizar usando transform_raw_matches (gera as 2 perspectivas por partida)
    transform_result = transform_raw_matches(raw_df, tour_clean)
    transformed_df = transform_result["table"]

    return {
        "raw_df": raw_df,
        "transformed_df": transformed_df,
        "total_post_cutoff": post_cutoff_count,
        "valid_count": len(valid_rows),
        "rejected_count": sum(rejected_reasons.values()),
        "rejected_reasons": rejected_reasons,
        "per_player": per_player,
    }
