"""Radar resumido (item 6 da instrucao): "quais partidas de hoje merecem
que eu abra a Betano para conferir?" -- respondido SO com criterios
estatisticos/documentados (nenhuma odd real foi consultada nesta fase).
Nunca chamado de "value bet" (instrucao item 7); o rotulo usado e
"CANDIDATO PARA CONFERIR ODDS".

Criterios (todos precisam ser verdadeiros, fixados a priori e documentados
em docs/013 secao 7 -- nao ajustados nos dados desta execucao):

  1. historico suficiente     -- sample_bucket_career em {medium_10_49,
                                   large_50_plus} (exclui cold_start e
                                   small_1_9);
  2. mercado liberado          -- `restricted == False` (a classificacao ja
                                   herdada da Fase 6.1/7: so ATP
                                   aces_player em Grass e restrito hoje);
  3. calibracao aprovada       -- `method_selected` != "unavailable" (o
                                   `negbin_r` do fold vigente existia para
                                   aquele tour/mercado/variante/janela);
  4. probabilidade nao trivial -- `extreme_probability == False` (nem essa
                                   linha nem o lado oposto passam de 90%);
  5. identidade confiavel      -- os DOIS jogadores da partida resolvidos
                                   por `exact` ou `alias` (fuzzy_review ou
                                   unresolved nunca viram candidato, mesmo
                                   que a linha tenha preco)."""

from __future__ import annotations

import pandas as pd

from . import config as cfg

_RELIABLE_RESOLUTION_METHODS = {"exact", "alias"}


def flag_candidates(prices: pd.DataFrame) -> pd.DataFrame:
    df = prices.copy()

    reasons = pd.DataFrame(index=df.index)
    reasons["historico_suficiente"] = df["sample_bucket_career"].isin(cfg.CANDIDATE_SAMPLE_BUCKETS_OK)
    reasons["mercado_liberado"] = ~df["restricted"]
    reasons["calibracao_disponivel"] = df["method_selected"] != "unavailable"
    reasons["probabilidade_nao_trivial"] = ~df["extreme_probability"]
    reasons["identidade_confiavel"] = (
        df["resolution_method_player"].isin(_RELIABLE_RESOLUTION_METHODS)
        & df["resolution_method_opponent"].isin(_RELIABLE_RESOLUTION_METHODS)
    )

    df["is_candidate"] = reasons.all(axis=1)
    blockers = reasons.apply(
        lambda row: ",".join(k for k, v in row.items() if not v), axis=1
    )
    df["candidate_blockers"] = blockers
    df["candidate_label"] = df["is_candidate"].map(
        {True: cfg.CANDIDATE_LABEL, False: ""}
    )
    return df


def build_daily_summary(prices_with_candidates: pd.DataFrame, resolved: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por partida: quantas linhas/mercados dela viraram
    CANDIDATO PARA CONFERIR ODDS, para responder rapido "o que vale abrir a
    Betano para conferir hoje"."""

    if prices_with_candidates.empty:
        return pd.DataFrame()

    match_ctx = resolved[resolved["usable_for_prediction"] & ~resolved["is_duplicate"]][
        ["tour", "tournament", "surface", "match_date", "round",
         "player_id_a", "resolved_name_a", "player_id_b", "resolved_name_b"]
    ].drop_duplicates(subset=["tour", "player_id_a", "player_id_b", "match_date"])

    match_id_map = {}
    for r in resolved.itertuples(index=False):
        if r.usable_for_prediction:
            match_id_map[f"FUTURE:{r.tour}:{r.raw_match_seq}"] = (r.player_id_a, r.player_id_b)

    g = (
        prices_with_candidates.groupby(["tour", "market", "match_id"])
        .agg(n_lines=("is_candidate", "size"), n_candidate_lines=("is_candidate", "sum"))
        .reset_index()
    )

    summary = (
        g.groupby(["tour", "match_id"])
        .agg(n_markets_with_candidates=("n_candidate_lines", lambda s: int((s > 0).sum())),
             n_candidate_lines_total=("n_candidate_lines", "sum"))
        .reset_index()
    )
    summary["player_id_a"] = summary["match_id"].map(lambda m: match_id_map.get(m, (None, None))[0])
    summary["player_id_b"] = summary["match_id"].map(lambda m: match_id_map.get(m, (None, None))[1])

    summary = summary.merge(
        match_ctx, on=["tour", "player_id_a", "player_id_b"], how="left",
    )
    summary["is_radar_candidate"] = summary["n_candidate_lines_total"] > 0
    summary["label"] = summary["is_radar_candidate"].map({True: cfg.CANDIDATE_LABEL, False: ""})

    cols = [
        "tour", "tournament", "surface", "match_date", "round",
        "resolved_name_a", "resolved_name_b", "n_markets_with_candidates",
        "n_candidate_lines_total", "is_radar_candidate", "label", "match_id",
    ]
    return summary[cols].sort_values(
        ["is_radar_candidate", "n_candidate_lines_total"], ascending=[False, False]
    ).reset_index(drop=True)
