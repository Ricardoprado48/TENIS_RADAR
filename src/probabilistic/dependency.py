"""Total de aces: soma assumindo independencia vs distribuicao ajustada
empiricamente (item 4).

Abordagem A ("independencia"): lambda_total = lambda_jogador + lambda_
adversario (mesma previsao pontual da Fase 4). A variancia de cada jogador
e derivada do PROPRIO `r` de aces_player (count_distribution_metrics.csv,
ajustado so no treino); assumindo independencia, var_total = var_A + var_B.
Um `r_independente` e obtido por metodo dos momentos a partir dessa soma
(mesmo metodo ja usado na Fase 4 -- count_dist.fit_negbin_r -- so que
aplicado a estatisticas ja agregadas em vez de reajustar do zero).

Abordagem B ("empirica"): o `r` ja ajustado na Fase 4 diretamente sobre o
alvo `target_total_aces_match` (mesma metodologia, sem assumir
independencia) -- e o que a Fase 4/5 ja usam como "melhor abordagem" para
total_aces_match.

Correlacao residual: corr(aces do jogador, aces do adversario) na MESMA
partida, medida diretamente no fold de teste (diagnostico, nao usado para
ajustar nenhum parametro).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from . import config as cfg
from .distributions import generate_line_grid


def residual_correlation(df: pd.DataFrame) -> dict:
    """corr(target_aces do jogador, target_aces do adversario) por partida,
    usando o mesmo self-join por match_id/opponent_id ja usado na Fase 4
    (rate_models.add_total_aces_predictions) -- aqui so para diagnostico."""

    right = df[["match_id", "player_id", "target_aces"]].rename(
        columns={"player_id": "_opp_player_id", "target_aces": "_opp_target_aces"}
    )
    merged = df.merge(right, left_on=["match_id", "opponent_id"], right_on=["match_id", "_opp_player_id"], how="left")
    a = pd.to_numeric(merged["target_aces"], errors="coerce")
    b = pd.to_numeric(merged["_opp_target_aces"], errors="coerce")
    mask = a.notna() & b.notna()
    n = int(mask.sum())
    if n < 2 or a[mask].std() == 0 or b[mask].std() == 0:
        return {"n_matches_x2": n, "corr": None}
    # cada partida aparece 2x (uma por perspectiva) -- a correlacao e
    # simetrica, entao n de "pares" nao precisa ser deduplicado para o valor
    # do coeficiente (so afeta o n reportado, que deixamos explicito).
    corr = float(np.corrcoef(a[mask], b[mask])[0, 1])
    return {"n_matches_x2": n, "corr": corr}


def independent_sum_r(lam_a: np.ndarray, r_a: float | None,
                       lam_b: np.ndarray, r_b: float | None) -> tuple[np.ndarray, np.ndarray]:
    """Retorna (lambda_total, r_independente_por_linha) assumindo
    independencia entre os dois jogadores da partida."""

    lam_a = np.asarray(lam_a, dtype="float64")
    lam_b = np.asarray(lam_b, dtype="float64")
    var_a = lam_a + (lam_a ** 2) / r_a if (r_a is not None and r_a > 0) else lam_a.copy()
    var_b = lam_b + (lam_b ** 2) / r_b if (r_b is not None and r_b > 0) else lam_b.copy()
    lam_total = lam_a + lam_b
    var_total = var_a + var_b
    with np.errstate(divide="ignore", invalid="ignore"):
        r_indep = np.where(var_total > lam_total, (lam_total ** 2) / (var_total - lam_total), np.nan)
    return lam_total, r_indep


def compare_independence_vs_empirical(test_df: pd.DataFrame, lam_total_col: str,
                                       r_empirical: float | None, train_mean_total: float,
                                       aces_player_pred_col: str, r_aces_player: float | None) -> dict:
    """Compara, no MESMO fold de teste e na MESMA grade de linhas, a
    Abordagem A (soma independente, r por linha via momentos) contra a
    Abordagem B (r empirico ajustado direto no alvo total)."""

    right = test_df[["match_id", "player_id", aces_player_pred_col]].rename(
        columns={"player_id": "_opp_player_id", aces_player_pred_col: "_opp_" + aces_player_pred_col}
    )
    merged = test_df.merge(right, left_on=["match_id", "opponent_id"], right_on=["match_id", "_opp_player_id"], how="left")

    lam_a = pd.to_numeric(merged[aces_player_pred_col], errors="coerce").to_numpy(dtype="float64")
    lam_b = pd.to_numeric(merged["_opp_" + aces_player_pred_col], errors="coerce").to_numpy(dtype="float64")
    actual_total = pd.to_numeric(merged[cfg.ACTUAL_COL["total_aces_match"]], errors="coerce").to_numpy(dtype="float64")

    lam_total_indep, r_indep = independent_sum_r(lam_a, r_aces_player, lam_b, r_aces_player)

    lines = generate_line_grid(train_mean_total, r_empirical)
    rows = []
    for line in lines:
        mask = np.isfinite(lam_total_indep) & np.isfinite(actual_total) & np.isfinite(r_indep) & (r_indep > 0)
        if mask.sum() == 0:
            continue
        actual_over = (actual_total[mask] > line).astype("float64")

        p_over_a = stats.nbinom.sf(line, r_indep[mask], r_indep[mask] / (r_indep[mask] + lam_total_indep[mask]))
        brier_a = float(np.mean((np.clip(p_over_a, 1e-6, 1 - 1e-6) - actual_over) ** 2))

        lam_emp = pd.to_numeric(merged[lam_total_col], errors="coerce").to_numpy(dtype="float64")[mask]
        mask_b = np.isfinite(lam_emp)
        if mask_b.sum() == 0 or r_empirical is None or r_empirical <= 0:
            brier_b = None
        else:
            actual_over_b = (actual_total[mask][mask_b] > line).astype("float64")
            p_over_b = stats.nbinom.sf(line, r_empirical, r_empirical / (r_empirical + lam_emp[mask_b]))
            brier_b = float(np.mean((np.clip(p_over_b, 1e-6, 1 - 1e-6) - actual_over_b) ** 2))

        rows.append({
            "line": line, "n": int(mask.sum()),
            "brier_independente": brier_a, "brier_empirico": brier_b,
        })
    return {"lines": rows}
