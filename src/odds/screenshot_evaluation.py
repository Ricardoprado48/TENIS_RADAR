"""LOTE G (docs/018_PWA_ARQUITETURA.md secao 14): adapter entre os
mercados CONFIRMADOS pelo LOTE F (`data/processed/bookmaker_confirmed/`)
e o pipeline JA EXISTENTE das Fases 9/10 (`src.odds.build.run` /
`src.decision.build.run`).

Nao recalcula nenhuma formula (implied_probability/edge/fair_odds/
minimum_odds/decision_state continuam sendo calculadas exclusivamente por
`src.odds.pricing_compare` e `src.decision.rules`) -- este modulo so:

  1. monta o dict de entrada que `src.odds.build.run(entries=[...])` ja
     espera (mesmo formato de `record_odds.py --input-json`), a partir de
     uma `ConfirmedExtraction`;
  2. chama `src.odds.build.run` (Fase 9) e `src.decision.build.run`
     (Fase 10) -- a MESMA persistencia append-only ja usada por
     `scripts/record_odds.py` e `scripts/evaluate_opportunities.py`, nunca
     uma segunda fonte de verdade;
  3. le de volta a linha ja classificada e devolve um resultado estruturado
     por mercado.

So avalia leitura CONFIRMADA (nunca a extracao bruta da IA -- item "FONTE
DOS DADOS" do pedido do LOTE G). Nao investiga Betano automaticamente
(`investigate_betano=False`, mesma restricao de R4/CLAUDE.md Sec.15).

LOTE H (docs/018 secao 22) acrescentou so o campo `forward_key` ao
resultado de cada mercado avaliado -- a MESMA chave natural (bookmaker,
tour, match_id, market, player, side, line, decimal_odds, collected_at) ja
usada internamente aqui para casar contra `evaluated`, exposta pra fora
so para o botao "Registrar no Forward Test" (LOTE H) poder identificar a
oportunidade sem duplicar o join ja feito nesta funcao. Nenhuma formula
nova, nenhum campo estatistico alterado.
"""

from __future__ import annotations

import pandas as pd

from src.decision import build as decision_build
from src.decision import config as decision_cfg
from src.screenshot_parser import extraction_storage, extractor
from src.screenshot_parser import storage as screenshot_storage
from src.screenshot_parser.models import ConfirmedExtraction, NormalizedMarket

from . import build as odds_build
from . import config as odds_cfg
from . import pricing_compare as pc

# item "LINGUAGEM DA PWA": rotulos de agrupamento visual (nunca substituem
# `decision_state`, que continua exposto tal como a Fase 10 calculou --
# secao 6.6 do docs/018: "CANDIDATO*" -> PASSOU, "OBSERVAR" fica separado,
# "DESCARTAR" -> NAO_PASSOU).
EVAL_PASSOU = "PASSOU_DO_LIMITE"
EVAL_OBSERVAR = "OBSERVAR"
EVAL_NAO_PASSOU = "NAO_PASSOU"
EVAL_SEM_MODELO = "SEM_AVALIACAO_DISPONIVEL"

_CLASSIFICATION_TO_LABEL = {
    decision_cfg.STATE_CANDIDATO_FORTE: EVAL_PASSOU,
    decision_cfg.STATE_CANDIDATO: EVAL_PASSOU,
    decision_cfg.STATE_CANDIDATO_FRACO: EVAL_PASSOU,
    decision_cfg.STATE_OBSERVAR: EVAL_OBSERVAR,
    decision_cfg.STATE_DESCARTAR: EVAL_NAO_PASSOU,
}

MSG_MERCADO_NAO_MODELADO = "Mercado ainda nao disponivel para avaliacao pelo modelo."

# item "MAPEAMENTO DE LINHAS": inverso de `src.odds.config.EDGE_STATUS_LABELS`
# -- usado so para achar a coluna `odd_minima_{label}` (ja calculada na
# Fase 9) que corresponde ao piso de edge do mercado (Fase 10), nunca para
# recalcular a odd minima.
_EDGE_LABEL_TO_PCT = {v: k for k, v in odds_cfg.EDGE_STATUS_LABELS.items()}


class UploadNotFoundError(LookupError):
    """`upload_id` nao corresponde a nenhum print gravado (mesma checagem
    que `api/services/screenshot_service.py` ja faz para /extract e
    /confirm -- verificada aqui tambem porque a leitura confirmada, por si
    so, nao distingue 'upload inexistente' de 'upload existe mas nunca foi
    confirmado')."""


class NoConfirmedExtractionError(LookupError):
    """Nao existe (ainda) nenhuma leitura CONFIRMADA para este upload_id --
    a extracao bruta da IA nunca e avaliada diretamente (item "FONTE DOS
    DADOS")."""


class MatchContextUnavailableError(LookupError):
    """Sem `tour` (via `ManualFileCalendarProvider`, mesmo contexto usado
    no LOTE F) nao e possivel casar nenhum mercado deste print contra o
    radar -- todos os mercados de uma mesma confirmacao compartilham o
    mesmo match_key/contexto, entao a avaliacao inteira e bloqueada aqui
    em vez de inventar um resultado parcial por mercado."""


def _nan_to_none(value):
    if value is None:
        return None
    try:
        if value != value:  # NaN
            return None
    except TypeError:
        pass
    return value


def _latest_confirmed(upload_id: str) -> ConfirmedExtraction:
    if screenshot_storage.find_screenshot(upload_id) is None:
        raise UploadNotFoundError(upload_id)
    confirmed = extraction_storage.list_confirmed(upload_id)
    if not confirmed:
        raise NoConfirmedExtractionError(upload_id)
    return confirmed[-1]


def _resolve_player_and_opponent(
    m: NormalizedMarket, *, player_a: str | None, player_b: str | None
) -> tuple[str | None, str | None]:
    if m.player is not None:
        norm = m.player.strip().lower()
        if player_a and norm == player_a.strip().lower():
            return m.player, player_b
        if player_b and norm == player_b.strip().lower():
            return m.player, player_a
        return m.player, None

    # mercado de partida (ex.: total_aces_match) -- o print nao identifica
    # um jogador especifico. `precos_por_linha.parquet` grava a MESMA
    # probabilidade/linha para os dois jogadores da partida (verificado
    # manualmente na Fase 8), entao usar player_a como ancora devolve a
    # mesma avaliacao que usar player_b.
    return player_a, player_b


def _entry_for_market(
    m: NormalizedMarket, *, tour: str, tournament: str | None,
    player_a: str | None, player_b: str | None, collected_at: str,
) -> dict | None:
    """`None` quando o mercado nao existe na grade suportada pelas Fases
    6/7/9/10 (`total_games`, por exemplo -- item "MERCADOS" do pedido:
    "verifique se existe suporte... antes de avalia-lo... Se nao existir:
    NAO inventar avaliacao")."""

    if m.market not in decision_cfg.ALLOWED_MARKETS:
        return None

    player, opponent = _resolve_player_and_opponent(m, player_a=player_a, player_b=player_b)
    side = (m.side or "").lower()

    entry = {
        "bookmaker": odds_cfg.DEFAULT_BOOKMAKER,
        "tour": tour,
        "market": m.market,
        "player": player,
        "opponent": opponent,
        "tournament": tournament,
        "line": m.model_line,
        "collected_at": collected_at,
        "source_method": "screenshot_confirmed",
        "source_url": None,
    }
    entry[f"{side}_odds"] = m.decimal_odds
    return entry


def _find_evaluated_row(evaluated: pd.DataFrame, entry: dict) -> dict | None:
    if evaluated.empty:
        return None

    side = "over" if "over_odds" in entry else "under"
    decimal_odds = entry.get("over_odds") if side == "over" else entry.get("under_odds")

    mask = (
        (evaluated["bookmaker"] == entry["bookmaker"])
        & (evaluated["tour"] == entry["tour"])
        & (evaluated["market"] == entry["market"])
        & (evaluated["player"] == entry["player"])
        & (evaluated["side"] == side)
        & (evaluated["line"] == float(entry["line"]))
        & (evaluated["decimal_odds"] == float(decimal_odds))
    )
    if "collected_at" in evaluated.columns:
        collected = pd.to_datetime(entry["collected_at"], format="mixed", utc=True)
        ev_collected = pd.to_datetime(evaluated["collected_at"], format="mixed", utc=True, errors="coerce")
        mask &= ev_collected == collected

    subset = evaluated[mask]
    if subset.empty:
        return None
    return subset.iloc[-1].to_dict()


def _minimum_odds_for_market(row: dict) -> float | None:
    """Le a coluna `odd_minima_{label}` correspondente ao PISO minimo de
    edge do mercado (`market_edge_floor`, ja calculado por
    `src.decision.build._evaluate_all`) -- nunca recalcula
    `minimum_acceptable_odds` aqui."""

    floor_label = row.get("market_edge_floor")
    pct = _EDGE_LABEL_TO_PCT.get(floor_label)
    if pct is None:
        return None
    return _nan_to_none(row.get(f"odd_minima_{pct}"))


def _base_result(m: NormalizedMarket) -> dict:
    return {
        "market": m.market,
        "player": m.player,
        "bookmaker_display": m.bookmaker_display,
        "model_line": m.model_line,
        "side": m.side,
        "bookmaker_odds": m.decimal_odds,
        "model_probability": None,
        "fair_odds": None,
        "minimum_odds": None,
        "decision_state": None,
        "evaluation_label": EVAL_SEM_MODELO,
        "evaluation_message": None,
        "staleness_status": None,
        "restricted": None,
        "technical": None,
        # LOTE H: chave natural (Fase 9/10) desta linha ja registrada em
        # opportunities_evaluated.parquet -- None quando nao ha linha
        # avaliada (mercado nao modelado ou erro), nunca inventada.
        "forward_key": None,
        "error": None,
    }


def evaluate_confirmed(upload_id: str) -> dict:
    """Ponto de entrada unico chamado pela API (item "ENDPOINT" do
    pedido). Le a leitura confirmada, avalia cada mercado suportado contra
    o pipeline ja existente das Fases 9/10, e devolve um dict serializavel
    (nunca um DataFrame) com um resultado por mercado, na MESMA ordem da
    leitura confirmada."""

    confirmed = _latest_confirmed(upload_id)

    context = extractor.get_match_context(confirmed.match_key)
    if context is None or not context.tour:
        raise MatchContextUnavailableError(confirmed.match_key)

    collected_at = confirmed.confirmed_at.isoformat()

    entries: list[dict] = []
    entry_index_by_pos: dict[int, int] = {}
    for pos, m in enumerate(confirmed.markets):
        entry = _entry_for_market(
            m, tour=context.tour, tournament=context.tournament,
            player_a=context.player_a, player_b=context.player_b,
            collected_at=collected_at,
        )
        if entry is not None:
            entry_index_by_pos[pos] = len(entries)
            entries.append(entry)

    if entries:
        odds_result = odds_build.run(entries=entries, investigate_betano=False)
        decision_result = decision_build.run()
        evaluated = decision_result["evaluated"]
    else:
        odds_result = {"errors": []}
        evaluated = pd.DataFrame()

    errors_by_index = {e["entry_index"]: e["error"] for e in odds_result.get("errors", [])}

    results = []
    for pos, m in enumerate(confirmed.markets):
        result = _base_result(m)

        if pos not in entry_index_by_pos:
            result["evaluation_message"] = MSG_MERCADO_NAO_MODELADO
            results.append(result)
            continue

        idx = entry_index_by_pos[pos]
        if idx in errors_by_index:
            result["error"] = errors_by_index[idx]
            result["evaluation_message"] = "Nao foi possivel avaliar esta leitura."
            results.append(result)
            continue

        entry = entries[idx]
        row = _find_evaluated_row(evaluated, entry)
        if row is None:
            result["error"] = "Avaliacao nao encontrada apos o registro na Fase 9/10."
            result["evaluation_message"] = "Nao foi possivel avaliar esta leitura."
            results.append(result)
            continue

        classification = row["classification"]
        restricted = row.get("restricted")
        matched = row.get("matched")

        result.update({
            "model_probability": _nan_to_none(row.get("operational_probability")),
            "fair_odds": _nan_to_none(row.get("fair_odds")),
            "minimum_odds": _minimum_odds_for_market(row),
            "decision_state": classification,
            "evaluation_label": _CLASSIFICATION_TO_LABEL.get(classification, EVAL_SEM_MODELO),
            "evaluation_message": row.get("explanation"),
            "staleness_status": row.get("staleness_bucket"),
            "restricted": bool(restricted) if restricted == restricted else None,
            "technical": {
                "implied_probability": _nan_to_none(row.get("implied_probability")),
                "model_edge": _nan_to_none(row.get("model_edge")),
                "sample_quality": row.get("sample_quality"),
                "matched": bool(matched) if matched == matched else None,
                "match_reason": row.get("match_reason") or None,
                "data_staleness_days": _nan_to_none(row.get("data_staleness_days")),
                "restricted_motivo": row.get("restricted_motivo"),
            },
            "forward_key": {
                "bookmaker": row.get("bookmaker"),
                "tour": row.get("tour"),
                "match_id": row.get("match_id"),
                "market": row.get("market"),
                "player": row.get("player"),
                "side": row.get("side"),
                "line": row.get("line"),
                "decimal_odds": row.get("decimal_odds"),
                "collected_at": row.get("collected_at"),
            },
        })
        results.append(result)

    stale = pc.staleness_warning(context.tour)

    return {
        "upload_id": confirmed.upload_id,
        "extraction_id": confirmed.extraction_id,
        "match_key": confirmed.match_key,
        "confirmed_at": confirmed.confirmed_at,
        "historical_data_cutoff": stale["historical_data_cutoff"],
        "data_staleness_days": stale["data_staleness_days"],
        "staleness_warning": stale["staleness_warning"],
        "results": results,
    }
