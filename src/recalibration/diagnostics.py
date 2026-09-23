"""Item 10: diagnostico de por que a Negative Binomial melhora o Brier
agregado (Fase 6) apesar de vencer o Poisson observacao-a-observacao em
so ~15-19% das linhas. Nao altera nenhuma distribuicao -- so mede.

Hipotese testada: o NegBin vence MENOS vezes, mas quando vence, vence por
uma margem MAIOR (evita os erros grandes do Poisson na cauda, onde a
variancia real excede a assumida pelo Poisson); quando perde, perde por
pouco. Isso explica um Brier medio menor com uma taxa de vitoria por linha
baixa."""

from __future__ import annotations

import numpy as np
import pandas as pd


def negbin_vs_poisson_diagnostics(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    d = df.dropna(subset=["p_over_negbin", "p_over_poisson", "actual_over"]).copy()
    d["sq_err_poisson"] = (d["p_over_poisson"] - d["actual_over"]) ** 2
    d["sq_err_negbin"] = (d["p_over_negbin"] - d["actual_over"]) ** 2
    d["diff"] = d["sq_err_poisson"] - d["sq_err_negbin"]  # >0 quando NegBin e melhor nessa linha

    rows = []
    for key, sub in d.groupby(group_cols, dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        negbin_wins = sub["diff"] > 0
        poisson_wins = sub["diff"] < 0
        row = dict(zip(group_cols, key))
        row.update({
            "n": len(sub),
            "brier_poisson": float(sub["sq_err_poisson"].mean()),
            "brier_negbin": float(sub["sq_err_negbin"].mean()),
            "pct_negbin_wins": float(negbin_wins.mean()),
            "pct_poisson_wins": float(poisson_wins.mean()),
            "margem_media_quando_negbin_vence": float(sub.loc[negbin_wins, "diff"].mean()) if negbin_wins.any() else None,
            "margem_media_quando_poisson_vence": float((-sub.loc[poisson_wins, "diff"]).mean()) if poisson_wins.any() else None,
            "soma_diff_liquida": float(sub["diff"].sum()),
        })
        rows.append(row)
    return pd.DataFrame(rows)
