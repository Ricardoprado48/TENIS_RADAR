"""Lambda + dispersao (r) -> probabilidade por linha .5, para partidas
futuras (item 4/5/8 da instrucao). Reaproveita, sem alterar, os mesmos tres
componentes ja testados nas Fases 5/6:

  - `src.probabilistic.selection.build_all_configs` -- qual (variant,
    window) usar por tour/mercado, com o mesmo tratamento especial de Grass
    ja decidido na Fase 6 (nunca redecidido aqui);
  - `data/outputs/phase4/metrics/count_distribution_metrics.csv` -- media de
    treino e dispersao Negative Binomial (`negbin_r`) ja ajustadas SOMENTE
    com dados <= 2025-12-31 (fold_2026), reaproveitadas tal como estao;
  - `src.probabilistic.distributions.generate_line_grid` /
    `line_probabilities` / `line_difficulty_bucket` -- mesmas formulas da
    Fase 6, so avaliadas em cima do lambda de uma partida sem resultado
    ainda.

So a distribuicao Negative Binomial e usada (mesma escolha operacional da
Fase 6/6.1/7 -- `p_over_negbin` e a unica coluna que chega a Fase 6.1).
Quando `negbin_r` nao esta disponivel para um tour/mercado/variante/janela,
nenhuma linha e gerada para esse mercado -- nunca cai de volta pra Poisson
silenciosamente (mesmo comportamento implicito da Fase 6.1, que so consome
`p_over_negbin`)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.probabilistic import config as prob_cfg
from src.probabilistic import distributions as dist
from src.probabilistic import selection as sel

from . import config as cfg


def load_market_configs() -> list[sel.MarketConfig]:
    return sel.build_all_configs()


def load_count_distribution_metrics() -> pd.DataFrame:
    return pd.read_csv(cfg.COUNT_DISTRIBUTION_METRICS_PATH)


def _cd_lookup(cd_df: pd.DataFrame, tour: str, market: str, variant: str, window: str) -> dict:
    sub = cd_df[
        (cd_df["tour"] == tour) & (cd_df["fold"] == cfg.CURRENT_FOLD) & (cd_df["market"] == market)
        & (cd_df["variant"] == variant) & (cd_df["window"] == window)
    ]
    if sub.empty:
        return {"train_mean": None, "negbin_r": None}
    row = sub.iloc[0]
    r = row["negbin_r"]
    return {
        "train_mean": float(row["train_mean"]) if pd.notna(row["train_mean"]) else None,
        "negbin_r": float(r) if pd.notna(r) else None,
    }


def build_predictions_by_line(
    future_rows: pd.DataFrame, configs: list[sel.MarketConfig], cd_df: pd.DataFrame,
) -> pd.DataFrame:
    """Uma linha por (jogador, partida futura, mercado, linha .5): mesma
    granularidade de `data/outputs/phase6/previsoes_por_linha.parquet`, sem
    coluna `actual`/`actual_over` (a partida ainda nao aconteceu)."""

    if future_rows.empty:
        return pd.DataFrame()

    out_parts = []
    for mc in configs:
        tour, market = mc.tour, mc.market
        sub = future_rows[future_rows["tour"] == tour]
        if sub.empty:
            continue

        base_info = _cd_lookup(cd_df, tour, market, mc.base_variant, mc.base_window)
        lines = dist.generate_line_grid(base_info["train_mean"], base_info["negbin_r"])
        if not lines:
            continue
        grass_info = _cd_lookup(cd_df, tour, market, mc.grass_variant, mc.grass_window)

        for surface_mask, variant, window, r_use, train_mean in [
            (sub["surface"] != "Grass", mc.base_variant, mc.base_window, base_info["negbin_r"], base_info["train_mean"]),
            (sub["surface"] == "Grass", mc.grass_variant, mc.grass_window, grass_info["negbin_r"], grass_info["train_mean"]),
        ]:
            pred_col = prob_cfg.pred_column_name(market, variant, window)
            if pred_col not in sub.columns:
                continue
            rows = sub.loc[surface_mask]
            if rows.empty:
                continue
            lam_all = pd.to_numeric(rows[pred_col], errors="coerce").to_numpy(dtype="float64")
            valid = np.isfinite(lam_all) & (lam_all > 0)
            if valid.sum() == 0:
                continue
            ctx = rows.loc[valid].reset_index(drop=True)
            lam = lam_all[valid]

            for line in lines:
                probs = dist.line_probabilities(lam, r_use, line)
                diff_bucket = dist.line_difficulty_bucket(line, lam, r_use)
                part = pd.DataFrame({
                    "tour": tour, "market": market, "fold": cfg.RADAR_FOLD_LABEL,
                    "match_id": ctx["match_id"], "player_id": ctx["player_id"],
                    "opponent_id": ctx["opponent_id"], "surface": ctx["surface"],
                    "tournament_date": ctx["tournament_date"],
                    "prior_matches_career": ctx["prior_matches_career"],
                    "sample_bucket_career": ctx["sample_bucket_career"],
                    "config_variant": variant, "config_window": window,
                    "lambda": lam, "negbin_r": r_use if r_use is not None else np.nan,
                    "train_mean": train_mean if train_mean is not None else np.nan,
                    "line": line, "line_difficulty": diff_bucket,
                    "p_over_negbin": probs["p_over_negbin"],
                    "p_under_negbin": probs["p_under_negbin"],
                    "p_over_poisson": probs["p_over_poisson"],
                    "p_under_poisson": probs["p_under_poisson"],
                })
                out_parts.append(part)

    if not out_parts:
        return pd.DataFrame()
    return pd.concat(out_parts, ignore_index=True)
