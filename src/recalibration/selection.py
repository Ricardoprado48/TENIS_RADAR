"""Criterio de selecao do metodo de calibracao (item 9): um metodo so
substitui a probabilidade bruta se melhorar Brier E ECE, nos DOIS folds
avaliaveis (2025 e 2026) -- nunca escolhido so pelo ECE agregado, e nunca
escolhido se depender de um unico fold."""

from __future__ import annotations

import pandas as pd

from . import config as cfg


def _fold_metrics(metrics_df: pd.DataFrame, tour: str, market: str, fold: str, method: str) -> dict | None:
    sub = metrics_df[(metrics_df["tour"] == tour) & (metrics_df["market"] == market)
                      & (metrics_df["fold"] == fold) & (metrics_df["method"] == method)]
    if sub.empty or sub.iloc[0]["n"] in (0, None):
        return None
    return sub.iloc[0].to_dict()


def select_method(metrics_df: pd.DataFrame, tour: str, market: str) -> dict:
    raw_by_fold = {f: _fold_metrics(metrics_df, tour, market, f, "raw") for f in cfg.EVALUABLE_FOLDS}
    if any(v is None for v in raw_by_fold.values()):
        return {"tour": tour, "market": market, "method_selected": "raw",
                "motivo": "sem metricas raw validas em algum fold avaliavel"}

    candidates_ok = {}
    detail_rows = []
    for method in ["platt", "isotonic"]:
        ok_all_folds = True
        for f in cfg.EVALUABLE_FOLDS:
            m = _fold_metrics(metrics_df, tour, market, f, method)
            raw = raw_by_fold[f]
            if m is None or m["brier"] is None or raw["brier"] in (None, 0):
                ok_all_folds = False
                detail_rows.append({"fold": f, "method": method, "melhora_brier": None, "melhora_ece": None, "ok": False})
                continue
            brier_rel_gain = (raw["brier"] - m["brier"]) / raw["brier"]
            ece_ok = (m["ece"] is None) or (raw["ece"] is None) or (m["ece"] <= raw["ece"])
            brier_ok = brier_rel_gain >= cfg.MIN_REL_BRIER_IMPROVEMENT
            ok = brier_ok and ece_ok
            ok_all_folds = ok_all_folds and ok
            detail_rows.append({"fold": f, "method": method, "melhora_brier": brier_rel_gain,
                                 "melhora_ece": None if (m["ece"] is None or raw["ece"] is None) else raw["ece"] - m["ece"],
                                 "ok": ok})
        candidates_ok[method] = ok_all_folds

    winners = [m for m, ok in candidates_ok.items() if ok]
    detail_df = pd.DataFrame(detail_rows)
    if not winners:
        return {"tour": tour, "market": market, "method_selected": "raw",
                "motivo": "nenhum metodo melhorou Brier (>= %.0f%%) e ECE de forma consistente nos dois folds avaliaveis" % (cfg.MIN_REL_BRIER_IMPROVEMENT * 100),
                "detalhe": detail_df}

    if len(winners) == 2:
        # desempate: maior melhora media de Brier entre os folds avaliaveis.
        avg_gain = {}
        for method in winners:
            gains = detail_df[(detail_df["method"] == method)]["melhora_brier"].dropna()
            avg_gain[method] = gains.mean() if len(gains) else -1
        chosen = max(avg_gain, key=avg_gain.get)
        motivo = f"platt e isotonic melhoraram nos dois folds; {chosen} venceu por maior ganho medio de Brier"
    else:
        chosen = winners[0]
        motivo = f"{chosen} foi o unico a melhorar Brier e ECE de forma consistente nos dois folds avaliaveis"

    return {"tour": tour, "market": market, "method_selected": chosen, "motivo": motivo, "detalhe": detail_df}
