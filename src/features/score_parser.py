"""Parser robusto do campo `score` (formato Sackmann).

Convencao Sackmann: cada set e reportado como "games_do_vencedor_da_partida-
games_do_perdedor_da_partida", nessa ordem, mesmo em sets que o perdedor da
partida venceu. Tie-breaks normais aparecem como "7-6(4)" (numero entre
parenteses = pontos do perdedor do set no tie-break). Tie-breaks de partida /
super tie-breaks (usados para decidir o set decisivo em alguns eventos,
principalmente duplas e alguns Challengers/ITF) aparecem entre colchetes,
ex.: "6-4 3-6 [10-7]".

Codigos especiais observados nos dados reais (ver investigacao point-in-time
antes de escrever este modulo): RET, W/O, DEF / "Def.", ABD, "Walkover", e
variantes com sufixo (ex. "RET+H61"). Nunca inventamos o resultado de um set
que nao foi concluido -- um token de set que nao atinge uma contagem valida
de set fechado (ex. "3-2", "0-0", "[0-1]") e tratado como fragmento parcial,
nao como set completo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Optional

import pandas as pd

_SET_RE = re.compile(r"^(\d+)-(\d+)(?:\((\d+)\))?$")
_BREAKER_RE = re.compile(r"^\[(\d+)-(\d+)\]$")

# tokens de status especial (case-insensitive). RET cobre variantes como
# "RET+H61" (codigo medico anexado) por usar startswith.
_WALKOVER_RE = re.compile(r"^(W/O|WALKOVER)$", re.IGNORECASE)
_DEFAULT_RE = re.compile(r"^DEF\.?$", re.IGNORECASE)
_ABANDONED_RE = re.compile(r"^ABD$", re.IGNORECASE)
_RETIRED_RE = re.compile(r"^RET", re.IGNORECASE)


@dataclass
class ScoreParseResult:
    raw: Optional[str]
    status: str  # completed | retired | walkover | defaulted | abandoned | missing | unparseable
    complete: bool  # True somente se o placar foi jogado ate o fim, sem ambiguidade
    n_sets_completed: int
    sets_won_winner: int
    sets_won_loser: int
    total_games: Optional[int]  # soma apenas dos sets normais concluidos (exclui super tie-break)
    winner_games: Optional[int]
    loser_games: Optional[int]
    game_diff: Optional[int]  # winner_games - loser_games
    has_tiebreak: bool
    n_tiebreaks: int
    has_match_tiebreak: bool  # partida usou super tie-break / match tie-break (colchetes)
    n_match_tiebreaks_completed: int
    has_partial_trailing_set: bool  # havia um fragmento de set inacabado (retirement/default no meio do set)
    parse_ok: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _empty_result(raw, status, parse_ok=False) -> ScoreParseResult:
    return ScoreParseResult(
        raw=raw, status=status, complete=False, n_sets_completed=0,
        sets_won_winner=0, sets_won_loser=0, total_games=None, winner_games=None,
        loser_games=None, game_diff=None, has_tiebreak=False, n_tiebreaks=0,
        has_match_tiebreak=False, n_match_tiebreaks_completed=0,
        has_partial_trailing_set=False, parse_ok=parse_ok,
    )


def _is_finished_normal_set(g1: int, g2: int) -> bool:
    hi, lo = max(g1, g2), min(g1, g2)
    if hi >= 6 and (hi - lo) >= 2:
        return True
    if hi == 7 and (hi - lo) == 1:  # 7-6 / 7-5 ja cobertos acima; 7-6 cai aqui
        return True
    return False


def _is_finished_breaker(g1: int, g2: int) -> bool:
    hi, lo = max(g1, g2), min(g1, g2)
    return hi >= 10 and (hi - lo) >= 2


def parse_score(raw) -> ScoreParseResult:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)) or pd.isna(raw):
        return _empty_result(raw, "missing")
    raw_str = str(raw).strip()
    if raw_str == "":
        return _empty_result(raw, "missing")

    tokens = raw_str.split()

    status = "completed"
    score_tokens = []
    status_tokens_found = 0
    for tok in tokens:
        if _WALKOVER_RE.match(tok):
            status = "walkover"
            status_tokens_found += 1
        elif _ABANDONED_RE.match(tok):
            status = "abandoned"
            status_tokens_found += 1
        elif _DEFAULT_RE.match(tok):
            status = "defaulted"
            status_tokens_found += 1
        elif _RETIRED_RE.match(tok):
            status = "retired"
            status_tokens_found += 1
        else:
            score_tokens.append(tok)

    if status == "walkover" and not score_tokens:
        return _empty_result(raw_str, "walkover", parse_ok=True)

    normal_sets = []  # list of (g1, g2, tb_pts_or_None, finished_bool)
    breakers = []  # list of (g1, g2, finished_bool)
    unparsed = 0
    for tok in score_tokens:
        m = _SET_RE.match(tok)
        if m:
            g1, g2 = int(m.group(1)), int(m.group(2))
            tb = int(m.group(3)) if m.group(3) is not None else None
            normal_sets.append((g1, g2, tb, _is_finished_normal_set(g1, g2)))
            continue
        m = _BREAKER_RE.match(tok)
        if m:
            g1, g2 = int(m.group(1)), int(m.group(2))
            breakers.append((g1, g2, _is_finished_breaker(g1, g2)))
            continue
        unparsed += 1

    if unparsed > 0 and not normal_sets and not breakers:
        return _empty_result(raw_str, "unparseable", parse_ok=False)

    finished_normal = [s for s in normal_sets if s[3]]
    unfinished_normal = [s for s in normal_sets if not s[3]]
    finished_breakers = [b for b in breakers if b[2]]
    unfinished_breakers = [b for b in breakers if not b[2]]

    sets_won_winner = sum(1 for g1, g2, *_ in finished_normal if g1 > g2)
    sets_won_winner += sum(1 for g1, g2, _fin in finished_breakers if g1 > g2)
    sets_won_loser = sum(1 for g1, g2, *_ in finished_normal if g2 > g1)
    sets_won_loser += sum(1 for g1, g2, _fin in finished_breakers if g2 > g1)

    total_games = sum(g1 + g2 for g1, g2, *_ in finished_normal) if finished_normal or normal_sets else None
    winner_games = sum(g1 for g1, g2, *_ in finished_normal) if finished_normal or normal_sets else None
    loser_games = sum(g2 for g1, g2, *_ in finished_normal) if finished_normal or normal_sets else None
    # se nao ha nenhum set normal no placar (ex. so colchete), nao ha games a somar
    if not normal_sets:
        total_games = None
        winner_games = None
        loser_games = None
    game_diff = (winner_games - loser_games) if (winner_games is not None and loser_games is not None) else None

    has_tiebreak = any(
        (max(g1, g2) == 7 and abs(g1 - g2) == 1) or tb is not None
        for g1, g2, tb, fin in finished_normal
    )
    n_tiebreaks = sum(
        1 for g1, g2, tb, fin in finished_normal
        if (max(g1, g2) == 7 and abs(g1 - g2) == 1) or tb is not None
    )

    has_match_tiebreak = len(breakers) > 0
    n_match_tiebreaks_completed = len(finished_breakers)
    has_partial_trailing_set = len(unfinished_normal) > 0 or len(unfinished_breakers) > 0

    n_sets_completed = len(finished_normal) + len(finished_breakers)

    complete = (
        status == "completed"
        and unparsed == 0
        and not has_partial_trailing_set
        and n_sets_completed > 0
    )

    return ScoreParseResult(
        raw=raw_str,
        status=status,
        complete=complete,
        n_sets_completed=n_sets_completed,
        sets_won_winner=sets_won_winner,
        sets_won_loser=sets_won_loser,
        total_games=total_games,
        winner_games=winner_games,
        loser_games=loser_games,
        game_diff=game_diff,
        has_tiebreak=has_tiebreak,
        n_tiebreaks=n_tiebreaks,
        has_match_tiebreak=has_match_tiebreak,
        n_match_tiebreaks_completed=n_match_tiebreaks_completed,
        has_partial_trailing_set=has_partial_trailing_set,
        parse_ok=(unparsed == 0),
    )


_RESULT_FIELDS = list(ScoreParseResult.__dataclass_fields__.keys())


def parse_score_column(scores: pd.Series) -> pd.DataFrame:
    """Aplica parse_score a uma coluna inteira e retorna um DataFrame alinhado
    pelo mesmo index, com uma coluna por campo de ScoreParseResult (exceto
    `raw`)."""

    parsed = scores.apply(parse_score)
    cols = {}
    for field in _RESULT_FIELDS:
        if field == "raw":
            continue
        cols[f"score_{field}"] = parsed.apply(lambda r: getattr(r, field))
    out = pd.DataFrame(cols, index=scores.index)

    int_cols = [
        "score_n_sets_completed", "score_sets_won_winner", "score_sets_won_loser",
        "score_total_games", "score_winner_games", "score_loser_games", "score_game_diff",
        "score_n_tiebreaks", "score_n_match_tiebreaks_completed",
    ]
    for c in int_cols:
        out[c] = pd.array(pd.to_numeric(out[c], errors="coerce"), dtype="Int64")
    bool_cols = ["score_complete", "score_has_tiebreak", "score_has_match_tiebreak",
                 "score_has_partial_trailing_set", "score_parse_ok"]
    for c in bool_cols:
        out[c] = out[c].astype("boolean")
    out["score_status"] = out["score_status"].astype("string")
    return out
