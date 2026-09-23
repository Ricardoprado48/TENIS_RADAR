"""Orquestrador da Fase 8.1: investiga fontes (item 1) -> integra partidas
novas se houver fonte adequada (itens 4-6) -> roda novamente o radar da
Fase 8 contra a base (possivelmente) atualizada -> compara com o radar
anterior (item 8) -> registra cobertura (item 9) e preservacao dos dados
originais (item 3).

Resultado desta execucao (2026-09-22): `sources.run_source_investigation()`
nao encontrou nenhuma fonte estruturada/HTTP que cubra estatisticas de
saque/devolucao para 2026-05-26..hoje sem contornar bloqueio anti-bot (ver
docs/014). Por isso `n_new_matches_incorporated == 0` nos dois tours nesta
execucao real, e o radar "depois" e gerado a partir dos MESMOS dados de
entrada do radar "antes" -- a comparacao (item 8) e, portanto, uma prova de
nao-regressao/idempotencia, nao uma medicao de melhora. O restante do
pipeline (investigacao, deduplicacao, resolucao de novos jogadores,
normalizacao, reconstrucao de features, comparacao) esta implementado e
testado com dados sinteticos em tests/test_incremental.py, pronto para
consumir dados reais assim que uma fonte adequada for aprovada."""

from __future__ import annotations

import hashlib
import json

import pandas as pd

from src.normalization.players import load_players
from src.radar import build as radar_build

from . import config as cfg
from . import merge
from . import sources as src_check


def _load_players_by_tour_lower() -> dict[str, pd.DataFrame]:
    return {tour: load_players(tour)[0] for tour in cfg.TOURS}


def _load_incremental_raw_files() -> dict[str, pd.DataFrame]:
    """Le `data/raw/incremental_2026/{tour}_novas_partidas.csv` (schema
    `cfg.RAW_SCHEMA_COLUMNS`, sem winner_id/loser_id), um por tour, se
    existir. Nesta execucao real nenhum arquivo desses existe (item 1:
    nenhuma fonte adequada) -- a funcao existe para consumir dados reais
    assim que uma fonte for aprovada, sem exigir nenhuma mudanca de codigo."""

    out = {}
    for tour in cfg.TOURS:
        path = cfg.INCREMENTAL_RAW_DIR / f"{tour}_novas_partidas.csv"
        if path.exists():
            out[tour] = pd.read_csv(path, dtype=str)
        else:
            out[tour] = pd.DataFrame(columns=[c for c in cfg.RAW_SCHEMA_COLUMNS if c not in ("winner_id", "loser_id")])
    return out


def _hash_preservation_snapshot() -> dict:
    """Hash dos arquivos originais da Fase 1 (data/raw/sackmann_*) e da
    Fase 2 (data/processed/{tour}/matches.parquet) -- comparado antes/depois
    para provar que nenhum foi sobrescrito (item 3 e item 10)."""

    out = {}
    for tour in cfg.TOURS:
        raw_path = cfg.RAW_DIRS[tour] / f"{tour}_matches_2026.csv"
        processed_path = cfg.PROCESSED_DIRS[tour] / "matches.parquet"
        if raw_path.exists():
            out[f"raw_{tour}"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        if processed_path.exists():
            out[f"processed_{tour}"] = hashlib.sha256(processed_path.read_bytes()).hexdigest()
    return out


def _compare_radar_outputs(radar_after_dir) -> pd.DataFrame:
    """Compara `precos_por_linha.parquet` do radar original (Fase 8,
    `data/outputs/phase8/`) com o gerado nesta fase, linha a linha, pelas
    chaves de mercado/linha/jogador (item 8: "mudanca de probabilidade...
    odd justa... odd minima")."""

    before_path = cfg.PHASE8_OUTPUT_DIR / "precos_por_linha.parquet"
    after_path = radar_after_dir / "precos_por_linha.parquet"
    if not before_path.exists() or not after_path.exists():
        return pd.DataFrame()

    before = pd.read_parquet(before_path)
    after = pd.read_parquet(after_path)

    key_cols = [c for c in ["match_id", "player_id", "market", "line", "side"] if c in before.columns and c in after.columns]
    metric_cols = [
        c for c in ["prior_matches_career", "calibrated_probability", "fair_odds", "sample_bucket_career"]
        if c in before.columns and c in after.columns
    ]
    if not key_cols:
        return pd.DataFrame()

    merged = before[key_cols + metric_cols].merge(
        after[key_cols + metric_cols], on=key_cols, how="outer", suffixes=("_antes", "_depois"), indicator=True,
    )
    merged["changed"] = merged["_merge"] != "both"
    for col in metric_cols:
        a, b = f"{col}_antes", f"{col}_depois"
        if pd.api.types.is_numeric_dtype(merged[a]):
            diff = (merged[a] - merged[b]).abs() > 1e-9
        else:
            diff = merged[a].astype(str) != merged[b].astype(str)
        merged["changed"] = merged["changed"] | diff.fillna(True)
    return merged


def _coverage_report(diagnostics_by_tour: dict, investigation: dict) -> pd.DataFrame:
    rows = []
    for tour, diag in diagnostics_by_tour.items():
        rows.append({
            "tour": tour,
            "n_new_matches_incorporated": diag["n_new_matches_incorporated"],
            "n_duplicates_skipped": diag["n_duplicates_skipped"],
            "n_new_players": diag["n_new_players"],
            "adequate_source_found": investigation["adequate_source_found"],
            "gap_start": "2026-05-26",
        })
    return pd.DataFrame(rows)


def run() -> dict:
    cfg.INCREMENTAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg.INCREMENTAL_RAW_DIR.mkdir(parents=True, exist_ok=True)

    hashes_before = _hash_preservation_snapshot()

    investigation = src_check.run_source_investigation()

    players_by_tour = _load_players_by_tour_lower()
    raw_by_tour = _load_incremental_raw_files()

    diagnostics_by_tour = {}
    overrides = {}
    for tour in cfg.TOURS:
        result = merge.integrate_incremental(tour, raw_by_tour[tour], players_by_tour[tour])
        diagnostics_by_tour[tour.upper()] = result["diagnostics"]
        if result["diagnostics"]["n_new_matches_incorporated"] > 0:
            merge.save_combined(tour, result["combined"])
            overrides[tour.upper()] = cfg.INCREMENTAL_PROCESSED_DIR / tour / "matches.parquet"

    coverage = _coverage_report(diagnostics_by_tour, investigation)
    coverage.to_csv(cfg.COVERAGE_CSV, index=False)

    radar_after_dir = cfg.INCREMENTAL_OUTPUT_DIR / "radar_atualizado"
    summary_after = radar_build.run(historical_overrides=overrides or None, output_dir=radar_after_dir)

    comparison = _compare_radar_outputs(radar_after_dir)
    comparison.to_csv(cfg.COMPARISON_CSV, index=False)

    hashes_after = _hash_preservation_snapshot()

    summary = {
        "generated_at_utc": str(pd.Timestamp.now("UTC")),
        "source_investigation": {
            "adequate_source_found": investigation["adequate_source_found"],
            "selected_source": investigation["selected_source"],
            "n_sources_checked": investigation["n_sources_checked"],
        },
        "coverage_by_tour": diagnostics_by_tour,
        "n_new_matches_total": sum(d["n_new_matches_incorporated"] for d in diagnostics_by_tour.values()),
        "radar_after_summary": summary_after,
        "n_price_rows_compared": len(comparison),
        "n_price_rows_changed": int(comparison["changed"].sum()) if not comparison.empty else 0,
        "historical_data_unchanged": hashes_before == hashes_after,
        "hashes_before": hashes_before,
        "hashes_after": hashes_after,
    }
    with open(cfg.SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
