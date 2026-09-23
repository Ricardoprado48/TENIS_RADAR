"""Orquestrador da Fase 10: le `comparison_with_model.parquet` (Fase 9),
enriquece (`inputs.py`) e classifica cada linha com `rules.evaluate_opportunity`,
gravando os 4 arquivos pedidos (item 14) em `data/outputs/phase10/`.

Cada oportunidade avaliada e persistida como um snapshot imutavel (item 13)
-- `opportunities_evaluated.parquet` e append-only, com a mesma logica de
dedup por chave completa (incluindo `collected_at`) ja usada na Fase 9.
`classification_summary.csv`/`rejected_opportunities.csv` sao VISOES do
estado atual (regeneradas a cada execucao, como `daily_odds_check.csv` da
Fase 9), nao ledgers.

Nao re-treina, nao recalibra, nao re-seleciona mercado, nao calcula stake,
nao faz aposta, nao cria interface."""

from __future__ import annotations

import json

import pandas as pd

from . import config as cfg
from . import inputs
from . import rules


def _evaluate_all(enriched: pd.DataFrame, market_edge_floor: dict | None = None) -> pd.DataFrame:
    if enriched.empty:
        return enriched

    records = []
    for row in enriched.to_dict(orient="records"):
        result = rules.evaluate_opportunity(row, market_edge_floor=market_edge_floor)
        rec = dict(row)
        rec["classification"] = result["classification"]
        rec["reasons"] = " | ".join(result["reasons"])
        rec["alerts"] = " | ".join(result["alerts"])
        rec["explanation"] = rules.format_explanation(result)
        rec["sample_quality"] = result["metrics"]["sample_quality"]
        rec["staleness_bucket"] = result["metrics"]["staleness_bucket"]
        rec["market_edge_floor"] = result["metrics"]["market_edge_floor"]
        rec["candidato_forte_capped_by_staleness"] = result["flags"]["candidato_forte_capped_by_staleness"]
        rec["stake_policy"] = result["stake_policy"]
        records.append(rec)
    return pd.DataFrame(records)


def _classification_summary(evaluated: pd.DataFrame) -> pd.DataFrame:
    if evaluated.empty:
        return pd.DataFrame()
    g = (
        evaluated.groupby(["tour", "market", "classification"], dropna=False)
        .size()
        .reset_index(name="n")
        .sort_values(["tour", "market", "classification"])
    )
    return g


def _rejected(evaluated: pd.DataFrame) -> pd.DataFrame:
    if evaluated.empty:
        return pd.DataFrame()
    rej = evaluated[evaluated["classification"] == cfg.STATE_DESCARTAR].copy()
    cols = [
        "bookmaker", "match_id", "tour", "market", "player", "side", "line",
        "decimal_odds", "collected_at", "model_edge", "status", "reasons",
    ]
    cols = [c for c in cols if c in rej.columns]
    return rej[cols]


def _sensitivity_report(enriched: pd.DataFrame) -> dict:
    """item 9: 'testar os thresholds existentes sem escolher ainda um unico
    padrao definitivo' -- compara a classificacao produzida pelo piso por
    mercado (`config.MARKET_MIN_EDGE_LABEL`) contra um piso UNIFORME
    (`config.SENSITIVITY_UNIFORM_EDGE_LABEL`), reportando quantas linhas
    mudam de classificacao -- nao escolhe qual dos dois e o correto."""

    if enriched.empty:
        return {"n_rows_compared": 0, "n_classification_changed": 0, "by_market": {}}

    per_market = _evaluate_all(enriched)["classification"]
    uniform_floor = {m: cfg.SENSITIVITY_UNIFORM_EDGE_LABEL for m in cfg.ALLOWED_MARKETS}
    uniform = _evaluate_all(enriched, market_edge_floor=uniform_floor)["classification"]

    changed = (per_market.reset_index(drop=True) != uniform.reset_index(drop=True))
    by_market = {}
    for market in cfg.ALLOWED_MARKETS:
        mask = enriched["market"].reset_index(drop=True) == market
        by_market[market] = {
            "n_rows": int(mask.sum()),
            "n_changed": int((changed & mask).sum()),
        }
    return {
        "n_rows_compared": int(len(enriched)),
        "n_classification_changed": int(changed.sum()),
        "by_market": by_market,
        "market_specific_floor": cfg.MARKET_MIN_EDGE_LABEL,
        "uniform_floor_tested": cfg.SENSITIVITY_UNIFORM_EDGE_LABEL,
    }


def _append_opportunities(new_rows: pd.DataFrame) -> pd.DataFrame:
    dedup_key = [
        "bookmaker", "match_id", "tour", "market", "player", "side", "line",
        "decimal_odds", "collected_at",
    ]
    dedup_key = [c for c in dedup_key if c in new_rows.columns]

    if cfg.OPPORTUNITIES_PATH.exists():
        existing = pd.read_parquet(cfg.OPPORTUNITIES_PATH)
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = new_rows.reset_index(drop=True)

    if dedup_key:
        combined = combined.drop_duplicates(subset=dedup_key, keep="first").reset_index(drop=True)

    cfg.PHASE10_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(cfg.OPPORTUNITIES_PATH, index=False)
    return combined


def _write_operational_rules() -> dict:
    rules_doc = {
        "states": cfg.STATES_ORDER,
        "forbidden_terms": cfg.FORBIDDEN_TERMS,
        "gates_item2": [
            "mercado_aprovado", "linha_existe_na_distribuicao",
            "previsao_nao_restrita", "identidade_confiavel",
            "probabilidade_operacional_valida", "odd_acima_do_limite_configurado",
            "amostra_historica_minima", "staleness_registrada",
        ],
        "edge_rank": cfg.EDGE_RANK,
        "sample_quality_thresholds": cfg.SAMPLE_QUALITY_THRESHOLDS,
        "staleness_policy": {
            "atual_max_days": cfg.STALENESS_ATUAL_MAX_DAYS,
            "moderado_max_days": cfg.STALENESS_MODERADO_MAX_DAYS,
            "max_staleness_days_for_candidato_forte": cfg.MAX_STALENESS_DAYS_FOR_CANDIDATO_FORTE,
        },
        "min_liquid_odds": cfg.MIN_LIQUID_ODDS,
        "market_min_edge_label": cfg.MARKET_MIN_EDGE_LABEL,
        "sensitivity_uniform_edge_label_tested": cfg.SENSITIVITY_UNIFORM_EDGE_LABEL,
        "stake_policy": cfg.STAKE_POLICY_NOT_IMPLEMENTED,
    }
    cfg.PHASE10_DIR.mkdir(parents=True, exist_ok=True)
    with open(cfg.OPERATIONAL_RULES_PATH, "w", encoding="utf-8") as f:
        json.dump(rules_doc, f, indent=2, default=str, ensure_ascii=False)
    return rules_doc


def run() -> dict:
    cfg.PHASE10_DIR.mkdir(parents=True, exist_ok=True)

    comparisons = pd.read_parquet(cfg.PHASE9_COMPARISON_PATH) if cfg.PHASE9_COMPARISON_PATH.exists() else pd.DataFrame()
    prices = inputs.load_radar_prices() if cfg.PHASE8_PRICES_PATH.exists() else pd.DataFrame()
    resolved = inputs.load_resolved_matches() if cfg.PHASE8_RESOLVED_PATH.exists() else pd.DataFrame()

    enriched = inputs.enrich_comparisons(comparisons, prices, resolved) if not comparisons.empty else comparisons
    evaluated = _evaluate_all(enriched)

    combined = _append_opportunities(evaluated) if not evaluated.empty else evaluated

    summary_view = evaluated if not evaluated.empty else combined
    classification_summary = _classification_summary(summary_view)
    rejected = _rejected(summary_view)

    cfg.PHASE10_DIR.mkdir(parents=True, exist_ok=True)
    classification_summary.to_csv(cfg.CLASSIFICATION_SUMMARY_PATH, index=False)
    rejected.to_csv(cfg.REJECTED_PATH, index=False)

    operational_rules = _write_operational_rules()
    sensitivity = _sensitivity_report(enriched)

    summary = {
        "n_opportunities_evaluated_this_run": int(len(evaluated)),
        "n_opportunities_total_ledger": int(len(combined)) if not combined.empty else 0,
        "classification_counts": (
            evaluated["classification"].value_counts().to_dict() if not evaluated.empty else {}
        ),
        "sensitivity_item9": sensitivity,
        "stake_policy": cfg.STAKE_POLICY_NOT_IMPLEMENTED,
    }
    with open(cfg.PHASE10_SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str, ensure_ascii=False)

    return {**summary, "operational_rules": operational_rules, "evaluated": evaluated}
