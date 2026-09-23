"""Transforma previsao pontual (lambda) + dispersao (r) em probabilidades
Over/Under para uma grade de linhas .5 (item 1/5).

lambda: previsao pontual por linha/jogador/partida, ja calculada na Fase 4
(pred_aces_*, pred_total_aces_*, pred_double_faults_*) -- nao recalculada
aqui.

r (Negative Binomial): parametro de dispersao ja ajustado na Fase 4 via
metodo dos momentos, usando SOMENTE o fold de TREINO
(data/outputs/phase4/metrics/count_distribution_metrics.csv, coluna
`negbin_r`) -- reaproveitado aqui, nunca reajustado. Quando `r` e None (sem
overdispersion detectavel no treino), o mercado/fold usa somente Poisson.

Distribuicao usada para gerar a GRADE de linhas: a mesma NegBin/Poisson
ajustada no treino, com media = train_mean (tambem de count_distribution_
metrics.csv) -- ou seja, a grade de linhas reflete a faixa historicamente
observada ANTES do periodo de teste (point-in-time-safe), nao os resultados
do proprio fold de teste.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from . import config as cfg


def negbin_pr(r: float, lam: np.ndarray) -> np.ndarray:
    return r / (r + lam)


def generate_line_grid(train_mean: float, r: float | None) -> list[float]:
    """Gera linhas .5 a partir dos quantis [LOW_Q, HIGH_Q] da distribuicao
    ajustada no TREINO (item 5: "a partir da faixa historica observada",
    "nao fixar limites arbitrarios")."""

    if train_mean is None or not np.isfinite(train_mean) or train_mean <= 0:
        return []
    if r is not None and np.isfinite(r) and r > 0:
        p = r / (r + train_mean)
        lo = stats.nbinom.ppf(cfg.LINE_GRID_LOW_Q, r, p)
        hi = stats.nbinom.ppf(cfg.LINE_GRID_HIGH_Q, r, p)
    else:
        lo = stats.poisson.ppf(cfg.LINE_GRID_LOW_Q, train_mean)
        hi = stats.poisson.ppf(cfg.LINE_GRID_HIGH_Q, train_mean)
    lo = max(0, int(lo) - 1)
    hi = int(hi) + 1
    lines = [x + 0.5 for x in range(lo, hi)]
    if len(lines) > cfg.MAX_LINES_PER_GROUP:
        # mantem uma grade centrada, cortando as pontas mais extremas em
        # vez de truncar de um lado so.
        excess = len(lines) - cfg.MAX_LINES_PER_GROUP
        cut_lo = excess // 2
        cut_hi = excess - cut_lo
        lines = lines[cut_lo: len(lines) - cut_hi]
    return lines


def line_probabilities(lam: np.ndarray, r: float | None, line: float) -> dict:
    """P(Over line) para Poisson e (quando r disponivel) Negative Binomial,
    ponto a ponto (um lambda por linha/jogador/partida -- item 1)."""

    lam = np.asarray(lam, dtype="float64")
    p_over_poisson = stats.poisson.sf(line, mu=lam)
    out = {"p_over_poisson": p_over_poisson, "p_under_poisson": 1.0 - p_over_poisson}
    if r is not None and np.isfinite(r) and r > 0:
        pr = negbin_pr(r, lam)
        p_over_nb = stats.nbinom.sf(line, r, pr)
        out["p_over_negbin"] = p_over_nb
        out["p_under_negbin"] = 1.0 - p_over_nb
    else:
        out["p_over_negbin"] = np.full_like(lam, np.nan)
        out["p_under_negbin"] = np.full_like(lam, np.nan)
    return out


def line_difficulty_bucket(line: float, lam: np.ndarray, r: float | None) -> np.ndarray:
    """Classifica cada linha, por linha/observacao, conforme a distancia (em
    desvios-padrao implicitos pelo modelo) entre a linha e a media prevista
    daquela linha/jogador/partida (item 7)."""

    lam = np.asarray(lam, dtype="float64")
    if r is not None and np.isfinite(r) and r > 0:
        var = lam + (lam ** 2) / r
    else:
        var = lam.copy()
    std = np.sqrt(np.clip(var, 1e-9, None))
    z = (line - lam) / std
    out = np.empty(z.shape, dtype=object)
    for lo, hi, label in cfg.LINE_DIFFICULTY_BUCKETS:
        mask = (z >= lo) & (z < hi)
        out[mask] = label
    return out
