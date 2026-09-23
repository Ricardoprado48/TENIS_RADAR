"""CLV -- Closing Line Value (item 10). Compara a odd usada no registro da
previsao (`decimal_odds`, congelada em `forward_predictions.parquet`) contra
`closing_odds_observed` (item 6 -- ultima leitura manual antes do inicio
informado da partida, `odds_snapshots.summarize_odds_movement`).

CLV positivo (`clv_pct > 0`) significa que a odd obtida era melhor que o
fechamento observado -- NUNCA interpretado isoladamente como prova de
lucratividade (item 10)."""

from __future__ import annotations

import pandas as pd

from src.pricing import odds as pricing_odds

from . import config as cfg

_CLV_COLUMNS = [
    "prediction_id", "tour", "market", "player", "side", "line",
    "odds_used", "closing_odds_observed", "first_observed_odds",
    "best_observed_odds", "n_snapshots", "clv_pct", "clv_probability_diff",
    "closing_odds_note",
]


def compute_clv(predictions: pd.DataFrame, odds_movement: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty or odds_movement.empty:
        return pd.DataFrame(columns=_CLV_COLUMNS)

    merged = predictions.merge(odds_movement, on="prediction_id", how="inner")
    if merged.empty:
        return pd.DataFrame(columns=_CLV_COLUMNS)

    rows = []
    for r in merged.to_dict(orient="records"):
        odds_used = r["decimal_odds"]
        closing = r.get("closing_odds_observed")
        if closing is None or closing != closing:
            continue

        clv_pct = (float(odds_used) / float(closing) - 1.0) * 100.0
        implied_used = float(pricing_odds.implied_probability(odds_used))
        implied_closing = float(pricing_odds.implied_probability(closing))

        rows.append({
            "prediction_id": r["prediction_id"],
            "tour": r.get("tour"), "market": r.get("market"), "player": r.get("player"),
            "side": r.get("side"), "line": r.get("line"),
            "odds_used": odds_used, "closing_odds_observed": closing,
            "first_observed_odds": r.get("first_observed_odds"),
            "best_observed_odds": r.get("best_observed_odds"),
            "n_snapshots": r.get("n_snapshots"),
            "clv_pct": clv_pct,
            "clv_probability_diff": implied_closing - implied_used,
            "closing_odds_note": r.get("closing_odds_note"),
        })

    out = pd.DataFrame(rows, columns=_CLV_COLUMNS)
    if not out.empty:
        cfg.PHASE11_DIR.mkdir(parents=True, exist_ok=True)
        out.to_parquet(cfg.CLV_ANALYSIS_PATH, index=False)
    return out
