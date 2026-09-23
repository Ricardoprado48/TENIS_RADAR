"""Funcoes puras de conversao probabilidade <-> odd (itens 2, 3, 9).

Todas operam vetorizadas (numpy) e retornam NaN para entradas invalidas em
vez de lancar excecao ou dividir por zero -- "nao calcular para
probabilidades invalidas ou ausentes" (item 2).
"""

from __future__ import annotations

import numpy as np


def fair_odds(p) -> np.ndarray:
    """odd_justa = 1 / p. Valido somente para 0 < p < 1 (p=0 ou p=1 sao
    degenerados/nao operacionais; NaN e propagado)."""

    p = np.asarray(p, dtype="float64")
    valid = np.isfinite(p) & (p > 0.0) & (p < 1.0)
    out = np.full_like(p, np.nan)
    out[valid] = 1.0 / p[valid]
    return out


def minimum_acceptable_odds(p, edge_required) -> np.ndarray:
    """odd_minima = 1 / (p - edge_required), somente quando p - edge_required > 0
    (item 3: "desde que p_modelo - e > 0"); caso contrario, NaN."""

    p = np.asarray(p, dtype="float64")
    e = np.asarray(edge_required, dtype="float64")
    p_implied_max = p - e
    valid = np.isfinite(p_implied_max) & (p_implied_max > 0.0)
    out = np.full_like(p_implied_max, np.nan)
    out[valid] = 1.0 / p_implied_max[valid]
    return out


def implied_probability(decimal_odds) -> np.ndarray:
    """implied_probability = 1 / decimal_odds (item 9), para uso futuro com
    odds reais observadas. Valido somente para odds > 1 (odd <= 1.0 nao e
    uma odd decimal operante)."""

    o = np.asarray(decimal_odds, dtype="float64")
    valid = np.isfinite(o) & (o > 1.0)
    out = np.full_like(o, np.nan)
    out[valid] = 1.0 / o[valid]
    return out


def edge(operational_probability, implied_probability_) -> np.ndarray:
    """edge = probabilidade do modelo - probabilidade implicita da odd
    observada (item 9). NaN se qualquer lado for NaN (propagacao natural do
    numpy)."""

    p = np.asarray(operational_probability, dtype="float64")
    q = np.asarray(implied_probability_, dtype="float64")
    return p - q
