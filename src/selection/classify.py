"""Classificacao objetiva CANDIDATO / EXPERIMENTAL / PAUSAR (item 8).

Regras fixadas em src/selection/config.py, aplicadas em ordem. Nenhum score
subjetivo: a decisao e uma funcao determinstica de (wins, melhora relativa
media, melhora minima por fold vencedor, cobertura, deterioracao por
superficie).
"""

from __future__ import annotations

import pandas as pd

from . import config as cfg


def classify_row(row: pd.Series, surface_flagged: bool) -> tuple[str, str]:
    wins = int(row["wins"])
    n_folds = int(row["n_folds"])
    mean_delta_rel = row["mean_delta_rel"]
    strong_wins = int(row["strong_wins"])
    coverage_ok = bool(row["coverage_ok_all_folds"])

    if not coverage_ok:
        return "PAUSAR", "cobertura insuficiente (n < %d) em pelo menos um fold" % cfg.MIN_COVERAGE_N

    if wins <= 1 or mean_delta_rel <= 0:
        return "PAUSAR", f"venceu o baseline em apenas {wins}/{n_folds} folds (ou melhora media <= 0)"

    if wins == n_folds and strong_wins == n_folds:
        if mean_delta_rel < cfg.MIN_MEAN_DELTA_REL:
            return "EXPERIMENTAL", (
                f"venceu em {wins}/{n_folds} folds mas melhora relativa media "
                f"({mean_delta_rel:.1%}) abaixo do limiar de {cfg.MIN_MEAN_DELTA_REL:.0%}"
            )
        if surface_flagged:
            return "EXPERIMENTAL", "venceu em todos os folds mas com deterioracao relevante em alguma superficie"
        return "CANDIDATO", (
            f"venceu o baseline em {wins}/{n_folds} folds, melhora relativa media "
            f"{mean_delta_rel:.1%}, sem deterioracao de superficie sinalizada"
        )

    if wins == n_folds and strong_wins < n_folds:
        return "EXPERIMENTAL", (
            f"venceu em {wins}/{n_folds} folds mas a melhora depende fortemente de "
            f"apenas {strong_wins} fold(s) (os demais venceram por margem residual)"
        )

    # wins == n_folds - 1 (ex.: 2/3)
    return "EXPERIMENTAL", f"venceu o baseline em {wins}/{n_folds} folds -- ganho nao consistente em todos os folds"


def classify_markets(best_df: pd.DataFrame, surface_df: pd.DataFrame) -> pd.DataFrame:
    flags = (
        surface_df.groupby(["tour", "market", "variant", "window"])["deterioration_flagged"]
        .any()
        .to_dict()
    )
    rows = []
    for _, r in best_df.iterrows():
        key = (r["tour"], r["market"], r["variant"], r["window"])
        flagged = bool(flags.get(key, False))
        decision, reason = classify_row(r, flagged)
        rows.append({
            "tour": r["tour"], "market": r["market"],
            "melhor_abordagem": f"{r['variant']}_{r['window']}",
            "wins": r["wins"], "n_folds": r["n_folds"], "strong_wins": r["strong_wins"],
            "mean_delta_rel": r["mean_delta_rel"], "mean_delta_abs": r["mean_delta_abs"],
            "std_delta_rel": r["std_delta_rel"],
            "surface_deterioration_flagged": flagged,
            "decisao": decision, "motivo": reason,
        })
    return pd.DataFrame(rows)
