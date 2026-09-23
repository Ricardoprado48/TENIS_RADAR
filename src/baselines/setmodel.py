"""Modelo analitico simples de jogos/sets/tie-break a partir de Hold% (item 2
"Total de games"/"Handicap"/"Total de sets"/"Tie-break" do CLAUDE.md #18, e a
comparacao explicita do item 3 da instrucao da Fase 4: "Hold% do sacador"
(isolado) vs "Hold% + Break%" (matchup)).

Metodologia: cadeia de Markov exata (nao Monte Carlo) sobre o placar de
games de UM set, dados p_hold_A (prob. de A segurar o proprio saque) e
p_hold_B (idem para B), com A sempre sacando primeiro no set (simplificacao
documentada -- o dado real alterna quem saca primeiro a cada set, mas isso
nao esta disponivel point-in-time nas features da Fase 3, e o efeito sobre
o numero esperado de games e de segunda ordem). Games sao um dado agregado
por partida na fonte Sackmann (nao ha placar ponto-a-ponto nem game-a-game),
entao qualquer coisa mais fina que isto exigiria um dado que nao temos --
ver docs/008 secao 4 para a limitacao.

O tie-break (6-6) nao tem probabilidade observavel diretamente (nao ha dado
de pontos), entao e aproximado por p_tb_A = p_hold_A / (p_hold_A + p_hold_B)
-- uma proxy simples e documentada (nao uma medicao), que preserva a
propriedade monotonica minima esperada (sacador/devolvedor mais forte tem
mais chance de fechar o tie-break).

Do set, a partida (best_of 3 ou 5) e agregada assumindo sets i.i.d. (mesma
p_set em todos os sets) -- outra simplificacao documentada, que ignora
momento/fadiga/mudanca de saque inicial entre sets.
"""

from __future__ import annotations

from functools import lru_cache
from math import comb

import numpy as np


def _is_set_terminal(a: int, b: int) -> bool:
    hi, lo = max(a, b), min(a, b)
    return hi >= 6 and (hi - lo) >= 2


def single_set_expectation(p_hold_a: float, p_hold_b: float) -> dict:
    """Retorna {p_a_wins_set, e_games_a, e_games_b, p_tiebreak} via cadeia de
    Markov exata sobre o placar de games (A saca games 1,3,5,...)."""

    if not (0.0 < p_hold_a < 1.0) or not (0.0 < p_hold_b < 1.0):
        p_hold_a = min(max(p_hold_a, 1e-6), 1 - 1e-6)
        p_hold_b = min(max(p_hold_b, 1e-6), 1 - 1e-6)

    # massa de probabilidade em cada estado transiente (a, b), 0<=a,b<=6
    mass = {(0, 0): 1.0}
    terminal_mass: dict[tuple[int, int], float] = {}
    tiebreak_mass = 0.0

    for total in range(0, 13):  # a+b de 0 a 12 (12 cobre 7-5/5-7/6-6)
        next_mass: dict[tuple[int, int], float] = {}
        for (a, b), m in mass.items():
            if a + b != total or m <= 0.0:
                continue
            if a == 6 and b == 6:
                tiebreak_mass += m
                continue
            if _is_set_terminal(a, b):
                terminal_mass[(a, b)] = terminal_mass.get((a, b), 0.0) + m
                continue
            server_is_a = (a + b) % 2 == 0
            p_a_wins_game = p_hold_a if server_is_a else (1 - p_hold_b)
            next_mass[(a + 1, b)] = next_mass.get((a + 1, b), 0.0) + m * p_a_wins_game
            next_mass[(a, b + 1)] = next_mass.get((a, b + 1), 0.0) + m * (1 - p_a_wins_game)
        mass = next_mass

    if tiebreak_mass > 0:
        p_tb_a = p_hold_a / (p_hold_a + p_hold_b)
        terminal_mass[(7, 6)] = terminal_mass.get((7, 6), 0.0) + tiebreak_mass * p_tb_a
        terminal_mass[(6, 7)] = terminal_mass.get((6, 7), 0.0) + tiebreak_mass * (1 - p_tb_a)

    p_a_wins_set = sum(m for (a, b), m in terminal_mass.items() if a > b)
    e_games_a = sum(m * a for (a, b), m in terminal_mass.items())
    e_games_b = sum(m * b for (a, b), m in terminal_mass.items())

    return {
        "p_a_wins_set": p_a_wins_set,
        "e_games_a": e_games_a,
        "e_games_b": e_games_b,
        "p_tiebreak": tiebreak_mass,
    }


def _best_of_n_sets_distribution(p_set_a: float, best_of: int) -> dict:
    """P(numero de sets == k) e P(A vence a partida), para best_of in {3,5},
    assumindo sets i.i.d. com prob. p_set_a de A vencer cada set (formula
    binomial negativa padrao para "melhor de N")."""

    sets_to_win = (best_of + 1) // 2  # 2 para best_of=3, 3 para best_of=5
    q = 1 - p_set_a
    dist = {}  # k -> (p_a_wins_in_k, p_b_wins_in_k)
    for loser_sets in range(0, sets_to_win):
        k = sets_to_win + loser_sets
        ways = comb(k - 1, loser_sets)
        p_a_k = ways * (p_set_a ** sets_to_win) * (q ** loser_sets)
        p_b_k = ways * (q ** sets_to_win) * (p_set_a ** loser_sets)
        dist[k] = (p_a_k, p_b_k)
    return dist


def match_expectation(p_hold_a: float, p_hold_b: float, best_of: int) -> dict:
    """Agrega o set unico para a partida inteira (best_of 3 ou 5)."""

    if best_of not in (3, 5):
        best_of = 3  # fallback conservador; nao deveria ocorrer com dados validos

    s = single_set_expectation(p_hold_a, p_hold_b)
    p_set_a = s["p_a_wins_set"]
    e_games_per_set = s["e_games_a"] + s["e_games_b"]
    e_diff_per_set = s["e_games_a"] - s["e_games_b"]
    p_tb_per_set = s["p_tiebreak"]

    dist = _best_of_n_sets_distribution(p_set_a, best_of)
    e_n_sets = sum(k * (pa + pb) for k, (pa, pb) in dist.items())
    p_sets_count = {k: pa + pb for k, (pa, pb) in dist.items()}

    p_no_tiebreak_any_set = (1 - p_tb_per_set) ** e_n_sets
    p_at_least_one_tiebreak = 1 - p_no_tiebreak_any_set

    return {
        "e_total_games": e_n_sets * e_games_per_set,
        "e_game_diff": e_n_sets * e_diff_per_set,
        "e_n_sets": e_n_sets,
        "p_sets_count": p_sets_count,  # {k: prob}
        "p_a_wins_match": sum(pa for pa, _ in dist.values()),
        "p_tiebreak_match": p_at_least_one_tiebreak,
        "p_set_a": p_set_a,
    }
