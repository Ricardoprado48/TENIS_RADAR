"""Comparacao entre odd observada e probabilidade operacional (itens 7, 8,
9, 10). Reaproveita `src.pricing.odds` (Fase 7) sem reimplementar nenhuma
formula: `implied_probability`, `edge` e `minimum_acceptable_odds` sao
exatamente as mesmas funcoes usadas para gerar `odds_minimas_por_edge.parquet`
na Fase 7/8.
"""

from __future__ import annotations

import pandas as pd

from src.pricing import odds as pricing_odds

from . import config as cfg


def classify_status(operational_probability: float, decimal_odds: float) -> str:
    """item 9: rotulo objetivo, nunca 'aposta garantida'/'certa'/'lucro
    garantido'. Percorre os edges do menor exigido ao maior (2% -> 10%) e
    devolve o maior edge atingido -- ABAIXO_DO_LIMITE se nenhum for."""

    if pd.isna(operational_probability) or pd.isna(decimal_odds):
        return cfg.STATUS_BELOW_THRESHOLD

    achieved = cfg.STATUS_BELOW_THRESHOLD
    for label, e in cfg.EDGE_LEVELS:
        min_odds = pricing_odds.minimum_acceptable_odds(operational_probability, e)
        min_odds = float(min_odds) if min_odds == min_odds else float("nan")  # NaN check sem numpy aqui
        if min_odds == min_odds and decimal_odds >= min_odds:
            achieved = cfg.EDGE_STATUS_LABELS[label]
    return achieved


def compare_one(operational_probability: float, decimal_odds: float) -> dict:
    """item 7: implied_probability, model_edge, e status por edge (item 9)."""

    implied = pricing_odds.implied_probability(decimal_odds)
    implied = float(implied) if implied == implied else float("nan")

    edge_val = float("nan")
    if implied == implied and not pd.isna(operational_probability):
        edge_val = float(pricing_odds.edge(operational_probability, implied))

    out = {
        "implied_probability": implied,
        "model_edge": edge_val,
        "status": classify_status(operational_probability, decimal_odds),
    }
    for label, e in cfg.EDGE_LEVELS:
        min_odds = pricing_odds.minimum_acceptable_odds(operational_probability, e)
        out[f"odd_minima_{label}"] = float(min_odds) if min_odds == min_odds else float("nan")
    return out


def overround_and_novig(over_odds: float | None, under_odds: float | None) -> dict:
    """item 8: soh calculado quando Over E Under estao disponiveis juntos.
    Nunca substitui o preco real (`over_odds`/`under_odds` continuam
    intocados no registro -- este dict e informativo/adicional)."""

    if over_odds is None or under_odds is None or pd.isna(over_odds) or pd.isna(under_odds):
        return {
            "implied_probability_over": float("nan"),
            "implied_probability_under": float("nan"),
            "overround": float("nan"),
            "novig_probability_over": float("nan"),
            "novig_probability_under": float("nan"),
        }

    p_over = float(pricing_odds.implied_probability(over_odds))
    p_under = float(pricing_odds.implied_probability(under_odds))
    overround = p_over + p_under - 1.0
    total = p_over + p_under
    novig_over = p_over / total if total > 0 else float("nan")
    novig_under = p_under / total if total > 0 else float("nan")
    return {
        "implied_probability_over": p_over,
        "implied_probability_under": p_under,
        "overround": overround,
        "novig_probability_over": novig_over,
        "novig_probability_under": novig_under,
    }


def staleness_warning(tour: str) -> dict:
    """item 10: defasagem estatistica sempre explicita, nunca escondida.
    Le somente o `max()` de `tournament_date` ja normalizado pela Fase 2 --
    nao reabre nenhuma feature."""

    path = cfg.DATA_PROCESSED / tour.lower() / "matches.parquet"
    hist = pd.read_parquet(path, columns=["tournament_date"])
    cutoff = pd.Timestamp(hist["tournament_date"].max())
    today = pd.Timestamp.now("UTC").tz_localize(None).normalize()
    gap_days = int((today - cutoff).days)
    return {
        "historical_data_cutoff": str(cutoff.date()),
        "data_staleness_days": gap_days,
        "staleness_warning": (
            f"Base historica atualizada ate {cutoff.date()} -- defasagem de "
            f"{gap_days} dias em relacao a hoje. Edge calculado nao deve ser "
            f"tratado como alta confianca so por ser grande (docs/014)."
        ),
    }
