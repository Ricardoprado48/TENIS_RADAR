"""Validacoes do LOTE F (docs/018 secao 7.4 e secoes "VALIDACOES"/
"CONFIDENCE / WARNINGS" do pedido).

`validate_and_normalize` nunca descarta uma leitura -- toda leitura bruta
vira exatamente uma `NormalizedMarket` na saida, com `warnings`/
`needs_confirmation` marcados quando algo estiver fora do esperado. Quem
decide o que fazer com um warning (bloquear ou so avisar) e a camada de
confirmacao (extractor.py::confirm_extraction), nao este modulo.
"""

from __future__ import annotations

from dataclasses import replace

from . import config as cfg
from . import mapping
from .models import MatchContext, NormalizedMarket, RawReading

# Formato ilegivel / odd invalida: a leitura nao tem um valor utilizavel
# (sem model_line/side, ou odd <= 1.00) -- erro estrutural grave.
WARN_FORMATO_ILEGIVEL = "FORMATO_ILEGIVEL"
WARN_ODD_INVALIDA = "ODD_INVALIDA"

# Demais warnings: a leitura tem um valor utilizavel, mas algo no contexto
# ou na consistencia do bloco pede revisao humana -- nunca bloqueiam
# sozinhos a confirmacao (docs "impedir apenas erros estruturais graves").
WARN_JOGADOR_NAO_RECONHECIDO = "JOGADOR_NAO_RECONHECIDO"
WARN_LEITURA_DUPLICADA = "LEITURA_DUPLICADA"
WARN_LINHAS_NAO_CRESCENTES = "LINHAS_NAO_CRESCENTES"
WARN_ODDS_NON_MONOTONIC = "ODDS_NON_MONOTONIC"
WARN_LINHA_SEM_PAR_OVER_UNDER = "LINHA_SEM_PAR_OVER_UNDER"
WARN_GAMES_ODDS_TENDENCIA_ATIPICA = "GAMES_ODDS_TENDENCIA_ATIPICA"

# Erros estruturais graves (secao "CONFIRMACAO": os unicos que impedem a
# confirmacao -- todo o resto pode ser confirmado manualmente pelo usuario
# mesmo com o warning presente).
STRUCTURAL_BLOCKING_WARNINGS = frozenset({WARN_FORMATO_ILEGIVEL, WARN_ODD_INVALIDA})


def _add_warning(m: NormalizedMarket, code: str) -> NormalizedMarket:
    if code in m.warnings:
        return m
    return replace(m, warnings=m.warnings + (code,), needs_confirmation=True)


def _normalize_one(reading: RawReading) -> NormalizedMarket:
    warnings: list[str] = []
    try:
        model_line, side = mapping.derive_line_and_side(reading.market, reading.bookmaker_display)
    except mapping.MappingError:
        model_line, side = None, None
        warnings.append(WARN_FORMATO_ILEGIVEL)

    if reading.decimal_odds is None or reading.decimal_odds <= 1.0:
        warnings.append(WARN_ODD_INVALIDA)

    return NormalizedMarket(
        market=reading.market,
        player=reading.player,
        bookmaker_display=reading.bookmaker_display,
        side=side,
        model_line=model_line,
        decimal_odds=reading.decimal_odds,
        confidence=reading.source_confidence,
        warnings=tuple(warnings),
        needs_confirmation=bool(warnings),
    )


def _check_player(markets: list[NormalizedMarket], context: MatchContext | None) -> list[NormalizedMarket]:
    if context is None:
        return markets
    known = {n.strip().lower() for n in (context.player_a, context.player_b) if n}
    if not known:
        return markets
    out = []
    for m in markets:
        if m.market == "aces_player" and m.player and m.player.strip().lower() not in known:
            m = _add_warning(m, WARN_JOGADOR_NAO_RECONHECIDO)
        out.append(m)
    return out


def _check_duplicates(markets: list[NormalizedMarket]) -> list[NormalizedMarket]:
    """Nao duplicar mesma combinacao market + player + side + model_line."""
    groups: dict[tuple, list[int]] = {}
    for i, m in enumerate(markets):
        key = (m.market, m.player, m.side, m.model_line)
        groups.setdefault(key, []).append(i)

    out = list(markets)
    for idxs in groups.values():
        if len(idxs) > 1:
            for i in idxs:
                out[i] = _add_warning(out[i], WARN_LEITURA_DUPLICADA)
    return out


def _check_aces_groups(markets: list[NormalizedMarket]) -> list[NormalizedMarket]:
    """Dentro do mesmo bloco (mesmo mercado + jogador/total): linhas devem
    ser crescentes, e a odd deve, em geral, crescer com a linha (warning,
    nao bloqueio -- ruido de arredondamento acontece em casas reais)."""
    groups: dict[tuple, list[int]] = {}
    for i, m in enumerate(markets):
        if m.market in ("aces_player", "total_aces_match") and m.model_line is not None:
            groups.setdefault((m.market, m.player), []).append(i)

    out = list(markets)
    for idxs in groups.values():
        lines_in_order = [out[i].model_line for i in idxs]
        if lines_in_order != sorted(lines_in_order):
            for i in idxs:
                out[i] = _add_warning(out[i], WARN_LINHAS_NAO_CRESCENTES)

        by_line = sorted(idxs, key=lambda i: out[i].model_line)
        prev_idx = None
        for i in by_line:
            odds = out[i].decimal_odds
            if prev_idx is not None and odds is not None and out[prev_idx].decimal_odds is not None:
                if odds < out[prev_idx].decimal_odds:
                    out[i] = _add_warning(out[i], WARN_ODDS_NON_MONOTONIC)
                    out[prev_idx] = _add_warning(out[prev_idx], WARN_ODDS_NON_MONOTONIC)
            prev_idx = i
    return out


def _check_games_pairs(markets: list[NormalizedMarket]) -> list[NormalizedMarket]:
    """Over e Under devem estar emparelhados na mesma linha; tendencia
    (Over sobe / Under desce conforme a linha aumenta) e so um warning
    opcional, nunca uma regra absoluta (pedido explicito)."""
    by_line: dict[float, dict[str, int]] = {}
    for i, m in enumerate(markets):
        if m.market == "total_games" and m.model_line is not None and m.side is not None:
            by_line.setdefault(m.model_line, {})[m.side] = i

    out = list(markets)
    for sides in by_line.values():
        if "Over" not in sides or "Under" not in sides:
            for i in sides.values():
                out[i] = _add_warning(out[i], WARN_LINHA_SEM_PAR_OVER_UNDER)

    over_points = sorted((line, idx["Over"]) for line, idx in by_line.items() if "Over" in idx)
    prev_odds = None
    for _, i in over_points:
        odds = out[i].decimal_odds
        if prev_odds is not None and odds is not None and odds < prev_odds:
            out[i] = _add_warning(out[i], WARN_GAMES_ODDS_TENDENCIA_ATIPICA)
        if odds is not None:
            prev_odds = odds

    under_points = sorted((line, idx["Under"]) for line, idx in by_line.items() if "Under" in idx)
    prev_odds = None
    for _, i in under_points:
        odds = out[i].decimal_odds
        if prev_odds is not None and odds is not None and odds > prev_odds:
            out[i] = _add_warning(out[i], WARN_GAMES_ODDS_TENDENCIA_ATIPICA)
        if odds is not None:
            prev_odds = odds

    return out


def validate_and_normalize(
    readings: list[RawReading],
    context: MatchContext | None = None,
) -> list[NormalizedMarket]:
    markets = [_normalize_one(r) for r in readings]
    markets = _check_player(markets, context)
    markets = _check_duplicates(markets)
    markets = _check_aces_groups(markets)
    markets = _check_games_pairs(markets)
    return markets


def is_structural_error(market: NormalizedMarket) -> bool:
    """Usado por extractor.py::confirm_extraction -- so isto bloqueia a
    confirmacao (secao "CONFIRMACAO" do pedido: "impedir apenas erros
    estruturais graves")."""
    if market.model_line is None or market.side is None:
        return True
    return any(w in STRUCTURAL_BLOCKING_WARNINGS for w in market.warnings)


def determine_status(markets: list[NormalizedMarket]) -> str:
    if not markets:
        return cfg.STATUS_NEEDS_CONFIRMATION
    if any(m.needs_confirmation for m in markets):
        return cfg.STATUS_NEEDS_CONFIRMATION
    return cfg.STATUS_AUTO_VALIDATED
