"""Persistencia append-only (item 6: 'nunca sobrescrever uma observacao
anterior -- odds sao snapshots temporais'). Cada chamada le o parquet
existente (se houver), concatena as novas linhas e regrava o arquivo
inteiro -- o EFEITO e append-only (nenhuma linha antiga e removida ou
alterada), mesmo que a implementacao em disco seja "ler tudo + regravar
tudo" (parquet nao suporta append nativo sem uma lib extra que o projeto
nao usa em nenhuma outra fase).
"""

from __future__ import annotations

import pandas as pd

from . import config as cfg


def _append(path, new_rows: pd.DataFrame, dedup_subset: list[str] | None = None) -> pd.DataFrame:
    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = new_rows.reset_index(drop=True)

    if dedup_subset:
        # item 14 (duplicacao): so descarta quando TODAS as colunas da chave
        # -- incluindo `collected_at` -- sao identicas a uma linha ja
        # gravada (reenvio exato do mesmo comando). Duas leituras da MESMA
        # linha em horarios diferentes continuam duas observacoes distintas
        # (item 11), porque `collected_at` difere.
        combined = combined.drop_duplicates(subset=dedup_subset, keep="first").reset_index(drop=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path, index=False)
    return combined


_OBSERVATION_DEDUP_KEY = cfg.OBSERVATION_COLUMNS


def append_observations(new_rows: pd.DataFrame) -> pd.DataFrame:
    return _append(cfg.ODDS_OBSERVED_PATH, new_rows, dedup_subset=_OBSERVATION_DEDUP_KEY)


def append_comparisons(new_rows: pd.DataFrame) -> pd.DataFrame:
    dedup_key = ["bookmaker", "match_id", "market", "player", "side", "line", "collected_at"]
    dedup_key = [c for c in dedup_key if c in new_rows.columns]
    return _append(cfg.COMPARISON_PATH, new_rows, dedup_subset=dedup_key or None)


def rebuild_snapshots_history() -> pd.DataFrame:
    """item 11: indexa a mesma serie de observacoes por
    (bookmaker, match_id, market, player, side, line), ordenada no tempo,
    com `snapshot_seq` e `line_move_from_previous` -- para permitir analise
    futura de movimentacao de linha/CLV sem precisar reprocessar
    `odds_observed.parquet` do zero."""

    if not cfg.ODDS_OBSERVED_PATH.exists():
        return pd.DataFrame()

    obs = pd.read_parquet(cfg.ODDS_OBSERVED_PATH).copy()
    obs["collected_at"] = pd.to_datetime(obs["collected_at"], format="mixed", utc=True)
    group_cols = ["bookmaker", "match_id", "market", "player", "side", "line"]
    obs = obs.sort_values(group_cols + ["collected_at"]).reset_index(drop=True)

    obs["snapshot_seq"] = obs.groupby(group_cols).cumcount() + 1
    obs["odds_previous"] = obs.groupby(group_cols)["decimal_odds"].shift(1)
    obs["line_move_from_previous"] = obs["decimal_odds"] - obs["odds_previous"]

    cfg.SNAPSHOTS_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    obs.to_parquet(cfg.SNAPSHOTS_HISTORY_PATH, index=False)
    return obs


def write_daily_check(comparison_rows: pd.DataFrame) -> pd.DataFrame:
    """`daily_odds_check.csv` e uma VISAO do estado atual (a observacao mais
    recente por bookmaker/partida/mercado/jogador/linha/lado), nao um
    ledger -- por isso e regenerada (sobrescrita) a cada execucao, ao
    contrario de `odds_observed.parquet`/`snapshots_history.parquet`, que
    nunca perdem uma linha antiga."""

    if not cfg.COMPARISON_PATH.exists():
        return pd.DataFrame()

    all_comparisons = pd.read_parquet(cfg.COMPARISON_PATH)
    if all_comparisons.empty:
        return all_comparisons

    all_comparisons = all_comparisons.copy()
    all_comparisons["collected_at"] = pd.to_datetime(all_comparisons["collected_at"], format="mixed", utc=True)
    group_cols = ["bookmaker", "match_id", "market", "player", "side", "line"]
    latest = (
        all_comparisons.sort_values("collected_at")
        .groupby(group_cols, as_index=False)
        .tail(1)
        .sort_values(["match_id", "market", "player", "line", "side"])
    )
    cfg.DAILY_CHECK_PATH.parent.mkdir(parents=True, exist_ok=True)
    latest.to_csv(cfg.DAILY_CHECK_PATH, index=False)
    return latest
