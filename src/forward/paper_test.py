"""Paper test flat (item 11) -- SOMENTE avaliacao, nunca dinheiro real,
nunca Kelly, nunca stake variavel, nunca recomendacao monetaria. 1 unidade
ficticia por oportunidade ELEGIVEL (`classification != DESCARTAR` -- uma
oportunidade `DESCARTAR` ja foi reprovada por um gate obrigatorio da Fase 10
e nunca seria de fato considerada operacionalmente, mas continua registrada
em `forward_predictions.parquet`, item 4). Rotulado explicitamente como
`config.PAPER_TEST_LABEL` em toda saida."""

from __future__ import annotations

import pandas as pd

from . import config as cfg


def _pnl_units(settlement: str, decimal_odds: float, stake: float):
    if settlement == cfg.SETTLEMENT_WIN:
        return (decimal_odds - 1.0) * stake
    if settlement == cfg.SETTLEMENT_LOSS:
        return -stake
    if settlement == cfg.SETTLEMENT_VOID:
        return 0.0
    return None  # UNRESOLVED / BOOKMAKER_RULE_REQUIRED -- ainda fora do P&L


def build_paper_test(predictions: pd.DataFrame, settlements: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty or settlements.empty:
        return pd.DataFrame()

    merged = predictions.merge(
        settlements[["prediction_id", "settlement", "settlement_reason", "settled_at"]],
        on="prediction_id", how="inner",
    )
    eligible = merged[merged["classification"].isin(cfg.PAPER_TEST_ELIGIBLE_CLASSIFICATIONS)].copy()
    if eligible.empty:
        return eligible

    eligible["stake_units"] = cfg.PAPER_TEST_FLAT_STAKE_UNITS
    eligible["pnl_units"] = [
        _pnl_units(s, o, cfg.PAPER_TEST_FLAT_STAKE_UNITS)
        for s, o in zip(eligible["settlement"], eligible["decimal_odds"])
    ]
    eligible["test_label"] = cfg.PAPER_TEST_LABEL

    resolved = eligible[eligible["pnl_units"].notna()].copy()
    if not resolved.empty:
        resolved = resolved.sort_values("settled_at")
        resolved["cumulative_pnl_units"] = resolved["pnl_units"].cumsum()
        running_max = resolved["cumulative_pnl_units"].cummax()
        resolved["drawdown_units"] = running_max - resolved["cumulative_pnl_units"]

        loss_streak, streaks = 0, []
        for s in resolved["settlement"]:
            loss_streak = loss_streak + 1 if s == cfg.SETTLEMENT_LOSS else 0
            streaks.append(loss_streak)
        resolved["running_loss_streak"] = streaks

        eligible = eligible.merge(
            resolved[["prediction_id", "cumulative_pnl_units", "drawdown_units", "running_loss_streak"]],
            on="prediction_id", how="left",
        )
    else:
        eligible["cumulative_pnl_units"] = None
        eligible["drawdown_units"] = None
        eligible["running_loss_streak"] = None

    cfg.PHASE11_DIR.mkdir(parents=True, exist_ok=True)
    eligible.to_parquet(cfg.PAPER_TEST_PATH, index=False)
    return eligible


def summarize_paper_test(paper_test_df: pd.DataFrame) -> dict:
    if paper_test_df.empty:
        return {"label": cfg.PAPER_TEST_LABEL, "n_entries_simulated": 0}

    resolved = paper_test_df[paper_test_df["pnl_units"].notna()]
    n_win = int((resolved["settlement"] == cfg.SETTLEMENT_WIN).sum())
    n_loss = int((resolved["settlement"] == cfg.SETTLEMENT_LOSS).sum())
    n_void = int((resolved["settlement"] == cfg.SETTLEMENT_VOID).sum())
    n_pending = int(len(paper_test_df) - len(resolved))

    staked_units = float(n_win + n_loss) * cfg.PAPER_TEST_FLAT_STAKE_UNITS
    total_pnl = float(resolved["pnl_units"].sum()) if not resolved.empty else 0.0
    roi = (total_pnl / staked_units) if staked_units > 0 else None

    return {
        "label": cfg.PAPER_TEST_LABEL,
        "n_entries_simulated": int(len(paper_test_df)),
        "n_wins": n_win, "n_losses": n_loss, "n_voids": n_void,
        "n_pending_settlement": n_pending,
        "total_staked_units": staked_units,
        "total_pnl_units": total_pnl,
        "roi": roi,
        "max_drawdown_units": float(resolved["drawdown_units"].max()) if not resolved.empty else None,
        "max_consecutive_losses": int(resolved["running_loss_streak"].max()) if not resolved.empty else None,
        "outcome_distribution": {"WIN": n_win, "LOSS": n_loss, "VOID": n_void, "PENDING": n_pending},
    }
