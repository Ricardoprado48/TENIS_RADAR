"""Mapeamento do rotulo da casa -> linha/lado do modelo (docs/018 secao
7.5 e secao "REGRAS" do pedido do LOTE F).

Regra unica, testavel isoladamente, sem estado -- nao decide nada sobre
validacao (isso fica em validator.py), so traduz o texto exibido pela
Betano para (model_line, side).
"""

from __future__ import annotations

import re

_ACES_PATTERN = re.compile(r"^\s*(\d+)\s*\+\s*$")
_GAMES_PATTERN = re.compile(r"^\s*(Mais|Menos)\s+de\s+(\d+(?:[.,]\d+)?)\s*$", re.IGNORECASE)

_GAMES_WORD_TO_SIDE = {"mais": "Over", "menos": "Under"}


class MappingError(ValueError):
    """`bookmaker_display` nao bate com nenhum formato conhecido para o
    mercado informado -- nunca inventa um valor, quem chama deve marcar a
    leitura para confirmacao humana."""


def map_aces_display(display: str) -> tuple[float, str]:
    """'X+' -> (X - 0.5, 'Over'). Regra do pedido: a Betano usa "no minimo
    X", o modelo usa "Over X-0.5". Vale para aces por jogador e total de
    aces da partida (mesmo formato de rotulo nos dois casos)."""
    match = _ACES_PATTERN.match(display or "")
    if not match:
        raise MappingError(f"Rotulo de aces nao reconhecido: {display!r}.")
    target = int(match.group(1))
    if target <= 0:
        raise MappingError(f"Alvo de aces deve ser um inteiro positivo: {display!r}.")
    return float(target) - 0.5, "Over"


def map_games_total_display(display: str) -> tuple[float, str]:
    """'Mais de N' -> (N, 'Over'); 'Menos de N' -> (N, 'Under') -- ja na
    mesma convencao do modelo, sem transformacao de "X+" (regra do
    pedido)."""
    match = _GAMES_PATTERN.match(display or "")
    if not match:
        raise MappingError(f"Rotulo de total de games nao reconhecido: {display!r}.")
    word, raw_line = match.groups()
    side = _GAMES_WORD_TO_SIDE[word.lower()]
    line = float(raw_line.replace(",", "."))
    return line, side


def derive_line_and_side(market: str, bookmaker_display: str) -> tuple[float, str]:
    """Despacha por mercado (secao "ESCOPO": so ACES e GAMES_TOTALS)."""
    if market in ("aces_player", "total_aces_match"):
        return map_aces_display(bookmaker_display)
    if market == "total_games":
        return map_games_total_display(bookmaker_display)
    raise MappingError(f"Mercado nao suportado por este mapeamento: {market!r}.")
