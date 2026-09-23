"""Leitura das saidas ja calculadas pelas Fases 9/10 para montar o registro
pre-jogo do item 3. Nenhuma probabilidade/odd/edge/classificacao e
recalculada aqui -- so um join read-only para completar 2 campos
descritivos (`tournament`, `opponent`) que `opportunities_evaluated.parquet`
(Fase 10) nao carrega, mas `odds_observed.parquet` (Fase 9) ja tem."""

from __future__ import annotations

import pandas as pd

from . import config as cfg

_JOIN_KEY = ["bookmaker", "match_id", "tour", "market", "player", "side", "line", "collected_at"]
_DESCRIPTIVE_COLS = ["tournament", "opponent"]


def load_phase10_opportunities() -> pd.DataFrame:
    if not cfg.PHASE10_OPPORTUNITIES_PATH.exists():
        return pd.DataFrame()
    return pd.read_parquet(cfg.PHASE10_OPPORTUNITIES_PATH)


def load_phase9_observations() -> pd.DataFrame:
    if not cfg.PHASE9_OBSERVATIONS_PATH.exists():
        return pd.DataFrame()
    return pd.read_parquet(cfg.PHASE9_OBSERVATIONS_PATH)


def enrich_with_match_context(opportunities: pd.DataFrame, observations: pd.DataFrame) -> pd.DataFrame:
    if opportunities.empty:
        return opportunities
    out = opportunities.copy()
    if observations.empty:
        for c in _DESCRIPTIVE_COLS:
            out[c] = None
        return out

    ctx = observations[_JOIN_KEY + _DESCRIPTIVE_COLS].drop_duplicates(subset=_JOIN_KEY)
    return out.merge(ctx, on=_JOIN_KEY, how="left")


def load_opportunities_for_registration(classifications: list[str] | None = None) -> pd.DataFrame:
    """item 4: por padrao devolve TODAS as classificacoes (nenhum filtro
    implicito) -- quem quiser restringir passa `classifications`
    explicitamente (uso pontual em testes/CLI, nunca politica default)."""

    opportunities = load_phase10_opportunities()
    observations = load_phase9_observations()
    enriched = enrich_with_match_context(opportunities, observations)
    if classifications and not enriched.empty:
        enriched = enriched[enriched["classification"].isin(classifications)]
    return enriched
