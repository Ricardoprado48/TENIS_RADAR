"""Odd justa e odd minima para partidas futuras (item 5 da instrucao).

Reaproveita, sem duplicar, as MESMAS funcoes da Fase 7
(`src.pricing.build.build_base` / `build_prices_by_line` /
`build_minimum_odds_by_edge`, e por baixo delas `src.pricing.odds` /
`src.pricing.flags`) -- a unica diferenca desta fase e a origem dos dados
de entrada (uma partida futura, em vez de uma linha ja resolvida
historicamente), nunca a formula. Isso garante, por construcao, que a
formula de odd justa/minima/restricao/flag e identica a que ja foi
documentada e testada em docs/012_ODDS_JUSTAS_FASE7.md."""

from __future__ import annotations

import pandas as pd

from src.pricing import build as pricing_build


def build_price_tables(calibrated_predictions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Retorna (base, precos_por_linha, odds_minimas_por_edge) no mesmo
    formato da Fase 7."""

    if calibrated_predictions.empty:
        empty = pd.DataFrame()
        return empty, empty, empty

    base = pricing_build.build_base(calibrated_predictions)
    prices = pricing_build.build_prices_by_line(base)
    min_odds = pricing_build.build_minimum_odds_by_edge(prices)
    return base, prices, min_odds
