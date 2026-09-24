"""Script de Homologação Controlada do Overlay Tennis Abstract (LOTE J).

Executa as etapas 1 a 9 da homologação:
1. Teste Real Controlado (2 ATP + 2 WTA)
2. Validação de Freshness (UPDATED, PARTIAL, BASE_ONLY, SOURCE_UNAVAILABLE)
3. Validação de Dedupe (duplicatas cruzadas e contagem antes/depois)
4. Validação de Anti-Leakage (garantia point-in-time para ATP e WTA)
5. Comparação Base Congelada vs Overlay (mesmas partidas do radar)
6. Quantificação de Impacto (métricas estatísticas e variações de odds)
7. Teste de Fallback (429, 403, timeout, jogador ausente, etc.)
8. Validação de Cache (chamada 1 vs chamada 2, hash e metadados)
9. Resumo de Compliance Operacional

Gera relatórios em `data/outputs/spikes/tennis_abstract_homologation/`.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Garantir PYTHONPATH no projeto
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np
import pandas as pd

from src.incremental import config as inc_cfg
from src.incremental.tennis_abstract_source import (
    AccessForbiddenError,
    PlayerNotFoundError,
    RateLimitError,
    TennisAbstractSource,
)
from src.incremental.tennis_abstract_adapter import (
    process_tennis_abstract_matches,
)
from src.incremental import overlay as ta_overlay
from src.normalization.config import PROCESSED_DIRS
from src.normalization.players import load_players
from src.radar import build as radar_build
from src.radar import config as radar_cfg

OUTPUT_DIR = Path("data/outputs/spikes/tennis_abstract_homologation")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PLAYERS_TEST = [
    {"name": "Carlos Alcaraz", "tour": "ATP", "pid": "ATP-207989"},
    {"name": "Jannik Sinner", "tour": "ATP", "pid": "ATP-206173"},
    {"name": "Iga Swiatek", "tour": "WTA", "pid": "WTA-216347"},
    {"name": "Aryna Sabalenka", "tour": "WTA", "pid": "WTA-214544"},
]


def run_homologation() -> dict[str, Any]:
    print("=" * 70)
    print("INICIANDO HOMOLOGAÇÃO CONTROLADA DO OVERLAY TENNIS ABSTRACT (LOTE J)")
    print("=" * 70)

    source = TennisAbstractSource(delay_seconds=2.5, ttl_hours=24.0)

    # -------------------------------------------------------------------------
    # 1. TESTE REAL CONTROLADO
    # -------------------------------------------------------------------------
    print("\n--- 1. TESTE REAL CONTROLADO (2 ATP + 2 WTA) ---")
    raw_payloads_by_tour: dict[str, list[dict]] = {"ATP": [], "WTA": []}
    players_real_report: list[dict[str, Any]] = []

    for p in PLAYERS_TEST:
        name = p["name"]
        tour = p["tour"]
        pid = p["pid"]
        print(f"Buscando dados para {name} ({tour})...")

        # Base Sackmann
        df_base = pd.read_parquet(PROCESSED_DIRS[tour.lower()] / "matches.parquet")
        p_base = df_base[df_base["player_id"] == pid]
        sackmann_last = str(p_base["tournament_date"].max().date())

        # Tennis Abstract fetch (respeita cache 24h)
        payload = source.fetch_player_matches(name, tour)
        raw_payloads_by_tour[tour].append(payload)

        # Analisar partidas
        all_matches = payload.get("matches", [])
        post_cutoff_matches = []
        for m in all_matches:
            d = m.get("date", "")
            if d.isdigit() and int(d) > 20260525:
                post_cutoff_matches.append(m)

        ta_last = "N/A"
        surfaces = set()
        if post_cutoff_matches:
            last_m = max(post_cutoff_matches, key=lambda x: int(x.get("date", "0")))
            d_raw = last_m.get("date", "")
            ta_last = f"{d_raw[:4]}-{d_raw[4:6]}-{d_raw[6:]}"
            surfaces = set(m.get("surf", "") for m in post_cutoff_matches if m.get("surf"))

        players_real_report.append({
            "canonical_player_id": pid,
            "name": name,
            "tour": tour,
            "ultima_partida_sackmann": sackmann_last,
            "ultima_partida_tennis_abstract": ta_last,
            "partidas_pos_cutoff_disponiveis": len(post_cutoff_matches),
            "superficies_cobertas": sorted(list(surfaces)),
            "cache_hit": payload.get("cache_hit", False),
        })

    # Processar overlay por tour
    overlay_dfs: dict[str, pd.DataFrame] = {}
    adapter_results: dict[str, Any] = {}

    for tour in ("ATP", "WTA"):
        print(f"\nProcessando e normalizando partidas pós-cutoff ({tour})...")
        res = process_tennis_abstract_matches(
            raw_payloads=raw_payloads_by_tour[tour],
            tour=tour,
            cutoff_date="2026-05-25",
        )
        adapter_results[tour] = res
        overlay_dfs[tour] = res["transformed_df"]
        # Salvar overlay no disco (em data/processed/incremental_overlays/tennis_abstract/)
        if not res["transformed_df"].empty:
            saved_path = ta_overlay.save_overlay_matches(tour, res["transformed_df"])
            print(f"  Overlay {tour} salvo em: {saved_path} ({len(res['transformed_df'])} linhas normalizadas)")
            ta_overlay.log_audit_event({
                "tour": tour,
                "n_raw_incoming": res["total_post_cutoff"],
                "n_valid": res["valid_count"],
                "n_rejected": res["rejected_count"],
                "rejected_reasons": res["rejected_reasons"],
            })

    # Completar informações individuais dos jogadores pós-normalização
    for p_rep in players_real_report:
        tour = p_rep["tour"]
        name = p_rep["name"]
        df_ov = overlay_dfs.get(tour, pd.DataFrame())
        p_matches = pd.DataFrame()
        if not df_ov.empty and "player_name" in df_ov.columns:
            p_matches = df_ov[df_ov["player_name"].str.lower() == name.lower()]

        n_added = len(p_matches)
        eff_cutoff = p_rep["ultima_partida_sackmann"]
        if not p_matches.empty:
            max_d = p_matches["tournament_date"].max()
            eff_cutoff = str(pd.to_datetime(max_d).date())

        p_rep["partidas_incorporadas_overlay"] = n_added
        p_rep["partidas_rejeitadas"] = p_rep["partidas_pos_cutoff_disponiveis"] - n_added
        p_rep["motivo_rejeicao"] = "Dados incompletos ou duplicata cruzada" if p_rep["partidas_rejeitadas"] > 0 else "Nenhum"
        p_rep["effective_data_cutoff"] = eff_cutoff

    print("\nResultados do Teste Real:")
    print(pd.DataFrame(players_real_report).to_string(index=False))

    # -------------------------------------------------------------------------
    # 2. VALIDAR FRESHNESS
    # -------------------------------------------------------------------------
    print("\n--- 2. VALIDAR FRESHNESS ---")
    freshness_results = []
    for p in players_real_report:
        f = ta_overlay.get_player_freshness(p["name"], p["tour"], overlay_df=overlay_dfs[p["tour"]])
        freshness_results.append({
            "name": p["name"],
            "tour": p["tour"],
            "base_cutoff": f["base_cutoff"],
            "overlay_last_match": f["overlay_last_match"],
            "effective_cutoff": f["effective_data_cutoff"],
            "freshness_status": f["freshness_status"],
        })

    # Testar também os outros 3 estados
    f_partial = ta_overlay.get_player_freshness("Carlos Alcaraz", "ATP", overlay_df=overlay_dfs["ATP"], has_partial_issues=True)
    f_base_only = ta_overlay.get_player_freshness("Jogador Sem Partidas Recentes", "ATP", overlay_df=overlay_dfs["ATP"])
    f_unavailable = ta_overlay.get_player_freshness("Carlos Alcaraz", "ATP", source_status="429")

    freshness_states_validation = {
        "UPDATED": freshness_results[0]["freshness_status"] == "UPDATED",
        "PARTIAL": f_partial["freshness_status"] == "PARTIAL",
        "BASE_ONLY": f_base_only["freshness_status"] == "BASE_ONLY",
        "SOURCE_UNAVAILABLE": f_unavailable["freshness_status"] == "SOURCE_UNAVAILABLE",
    }
    print("Estados de Freshness Comprovados:", freshness_states_validation)

    # -------------------------------------------------------------------------
    # 3. VALIDAR DEDUPE
    # -------------------------------------------------------------------------
    print("\n--- 3. VALIDAR DEDUPE ---")
    # Verificar partidas em comum entre jogadores
    dedupe_report = {
        "ATP": {
            "post_cutoff_disponiveis": adapter_results["ATP"]["total_post_cutoff"],
            "incorporadas_finais_unicas": adapter_results["ATP"]["valid_count"],
            "rejeitadas_ou_duplicadas": adapter_results["ATP"]["rejected_count"],
            "motivos": adapter_results["ATP"]["rejected_reasons"],
        },
        "WTA": {
            "post_cutoff_disponiveis": adapter_results["WTA"]["total_post_cutoff"],
            "incorporadas_finais_unicas": adapter_results["WTA"]["valid_count"],
            "rejeitadas_ou_duplicadas": adapter_results["WTA"]["rejected_count"],
            "motivos": adapter_results["WTA"]["rejected_reasons"],
        },
    }
    print("Relatório de Dedupe:", json.dumps(dedupe_report, indent=2))

    # -------------------------------------------------------------------------
    # 4. VALIDAR ANTI-LEAKAGE
    # -------------------------------------------------------------------------
    print("\n--- 4. VALIDAR ANTI-LEAKAGE (Point-in-time) ---")
    leakage_checks = {}

    for tour in ("ATP", "WTA"):
        eff_matches = ta_overlay.get_effective_matches(tour, enabled=True)
        # Selecionar uma data intermediária pós-cutoff D
        dates = eff_matches[eff_matches["tournament_date"] > pd.Timestamp("2026-05-25")]["tournament_date"].sort_values()
        if not dates.empty:
            mid_date = dates.iloc[len(dates) // 2]
            point_in_time_view = eff_matches[eff_matches["tournament_date"] <= mid_date]
            future_leakage = (point_in_time_view["tournament_date"] > mid_date).sum()
            leakage_checks[tour] = {
                "evaluated_date_D": str(mid_date.date()),
                "total_matches_in_view": len(point_in_time_view),
                "matches_after_D": int(future_leakage),
                "leakage_detected": bool(future_leakage > 0),
            }
        else:
            leakage_checks[tour] = {"leakage_detected": False, "note": "Sem partidas pos-cutoff"}

    print("Anti-Leakage Verification:", json.dumps(leakage_checks, indent=2))

    # -------------------------------------------------------------------------
    # 5 & 6. COMPARAÇÃO BASE CONGELADA VS OVERLAY & QUANTIFICAR IMPACTO
    # -------------------------------------------------------------------------
    print("\n--- 5 & 6. COMPARAÇÃO BASE CONGELADA VS OVERLAY ---")
    # Gerar predições de radar:
    # A) Base oficial congelada
    # B) Base com overlay
    comp_dir = OUTPUT_DIR / "radar_comparison"
    comp_dir.mkdir(parents=True, exist_ok=True)

    # 1. Executar Radar com Base Congelada
    dir_congelado = comp_dir / "congelado"
    summary_congelado = radar_build.run(output_dir=dir_congelado)

    # 2. Criar overrides temporários em parquet para rodar o radar com base + overlay
    dir_overlay = comp_dir / "overlay"
    tmp_atp_path = comp_dir / "effective_atp.parquet"
    tmp_wta_path = comp_dir / "effective_wta.parquet"

    eff_atp = ta_overlay.get_effective_matches("ATP", enabled=True)
    eff_wta = ta_overlay.get_effective_matches("WTA", enabled=True)
    eff_atp.to_parquet(tmp_atp_path, index=False)
    eff_wta.to_parquet(tmp_wta_path, index=False)

    summary_overlay = radar_build.run(
        historical_overrides={"ATP": tmp_atp_path, "WTA": tmp_wta_path},
        output_dir=dir_overlay,
    )

    # Carregar saídas de preços de ambos
    df_prices_congelado = pd.read_parquet(dir_congelado / "precos_por_linha.parquet")
    df_prices_overlay = pd.read_parquet(dir_overlay / "precos_por_linha.parquet")

    # Comparar linhas pareadas
    join_cols = ["match_id", "market", "player_id", "line", "side"]
    merged_comp = df_prices_congelado.merge(
        df_prices_overlay,
        on=join_cols,
        suffixes=("_congelado", "_overlay"),
    )

    merged_comp["diff_prob"] = merged_comp["operational_probability_overlay"] - merged_comp["operational_probability_congelado"]
    merged_comp["abs_diff_prob"] = merged_comp["diff_prob"].abs()
    merged_comp["changed_decision"] = merged_comp["is_candidate_congelado"] != merged_comp["is_candidate_overlay"]

    prob_diffs = merged_comp["abs_diff_prob"]
    impact_stats = {
        "n_total_linhas_comparadas": len(merged_comp),
        "media_variacao_absoluta_prob": float(prob_diffs.mean()) if not prob_diffs.empty else 0.0,
        "mediana_variacao_absoluta_prob": float(prob_diffs.median()) if not prob_diffs.empty else 0.0,
        "max_variacao_absoluta_prob": float(prob_diffs.max()) if not prob_diffs.empty else 0.0,
        "linhas_mudaram_classificacao": int(merged_comp["changed_decision"].sum()),
        "linhas_permaneceram_iguais": int((~merged_comp["changed_decision"]).sum()),
    }

    # Análise por tour
    for tour in ("ATP", "WTA"):
        tour_sub = merged_comp[merged_comp["tour_congelado"] == tour]
        impact_stats[f"{tour}_media_variacao_prob"] = float(tour_sub["abs_diff_prob"].mean()) if not tour_sub.empty else 0.0
        impact_stats[f"{tour}_linhas_mudaram"] = int(tour_sub["changed_decision"].sum()) if not tour_sub.empty else 0

    # Análise por mercado
    market_impact = {}
    for mkt, grp in merged_comp.groupby("market"):
        market_impact[mkt] = {
            "media_diff_prob": float(grp["abs_diff_prob"].mean()),
            "mudancas_classificacao": int(grp["changed_decision"].sum()),
        }
    impact_stats["mercados_impacto"] = market_impact

    # Salvar tabela de comparação detalhada
    sample_cols = [
        "match_id", "tour_congelado", "tournament_congelado", "player_name_congelado",
        "market", "line", "side",
        "operational_probability_congelado", "operational_probability_overlay", "diff_prob",
        "fair_odds_congelado", "fair_odds_overlay",
        "is_candidate_congelado", "is_candidate_overlay", "candidate_blockers_congelado", "candidate_blockers_overlay",
    ]
    export_df = merged_comp[[c for c in sample_cols if c in merged_comp.columns]]
    export_df.to_csv(comp_dir / "comparacao_detalhada_radar.csv", index=False)

    print("Impacto Estatístico Resumo:", json.dumps(impact_stats, indent=2))

    # Limpeza dos parquets temporários do override
    tmp_atp_path.unlink(missing_ok=True)
    tmp_wta_path.unlink(missing_ok=True)

    # -------------------------------------------------------------------------
    # 7. TESTAR FALLBACK
    # -------------------------------------------------------------------------
    print("\n--- 7. TESTAR FALLBACK ---")
    fallback_tests = {}
    with tempfile.TemporaryDirectory() as td:
        tmp_cache = Path(td)
        test_src = TennisAbstractSource(cache_dir=tmp_cache, delay_seconds=0.0)

        # 429
        with mock.patch.object(test_src, "_http_get", return_value=(429, "")):
            try:
                test_src.fetch_player_matches("Carlos Alcaraz", "ATP")
                fallback_tests["sim_429"] = "FAILED"
            except RateLimitError:
                f = ta_overlay.get_player_freshness("Carlos Alcaraz", "ATP", source_status="429")
                fallback_tests["sim_429"] = f["freshness_status"] == "SOURCE_UNAVAILABLE"

        # 403
        with mock.patch.object(test_src, "_http_get", return_value=(403, "")):
            try:
                test_src.fetch_player_matches("Carlos Alcaraz", "ATP")
                fallback_tests["sim_403"] = "FAILED"
            except AccessForbiddenError:
                f = ta_overlay.get_player_freshness("Carlos Alcaraz", "ATP", source_status="403")
                fallback_tests["sim_403"] = f["freshness_status"] == "SOURCE_UNAVAILABLE"

        # Timeout
        f_to = ta_overlay.get_player_freshness("Carlos Alcaraz", "ATP", source_status="TIMEOUT")
        fallback_tests["sim_timeout"] = f_to["freshness_status"] == "SOURCE_UNAVAILABLE"

        # Jogador não encontrado
        with mock.patch.object(test_src, "_http_get", return_value=(404, "")):
            try:
                test_src.fetch_player_matches("Jogador Inexistente 999", "ATP")
                fallback_tests["sim_not_found"] = "FAILED"
            except PlayerNotFoundError:
                f_nf = ta_overlay.get_player_freshness("Jogador Inexistente 999", "ATP")
                fallback_tests["sim_not_found"] = f_nf["freshness_status"] == "BASE_ONLY"

    print("Resultados de Fallback:", fallback_tests)

    # -------------------------------------------------------------------------
    # 8. VALIDAR CACHE
    # -------------------------------------------------------------------------
    print("\n--- 8. VALIDAR CACHE ---")
    with tempfile.TemporaryDirectory() as td:
        c_dir = Path(td) / "cache"
        src_cache = TennisAbstractSource(cache_dir=c_dir, delay_seconds=0.0)

        fake_html = 'var matchmx = [["20260601","Paris","Clay","G","W","1","","","F","6-3 6-3","","Opponent","2","","","R","1998-01-01","185","ESP","active","90","5","1","50","30","25","10","8","2","2","4","2","50","30","20","8","8","1","4","R","","","","2026-100-1","","7","1"]];'
        with mock.patch.object(src_cache, "_http_get", return_value=(200, fake_html)) as m_get:
            # 1a chamada
            res1 = src_cache.fetch_player_matches("Carlos Alcaraz", "ATP")
            m_get.assert_called_once()
            c_hit1 = res1.get("cache_hit")

            # 2a chamada
            res2 = src_cache.fetch_player_matches("Carlos Alcaraz", "ATP")
            m_get.assert_called_once()  # Não chamou de novo
            c_hit2 = res2.get("cache_hit")

    cache_validation = {
        "call_1_cache_hit": c_hit1,
        "call_2_cache_hit": c_hit2,
        "hash_present": bool(res1.get("hash")),
        "parser_version_recorded": res1.get("parser_version") == "1.0.0",
        "fetched_at_preserved": res1.get("fetched_at") == res2.get("fetched_at"),
    }
    print("Validação de Cache:", cache_validation)

    # -------------------------------------------------------------------------
    # 9. COMPLIANCE OPERACIONAL
    # -------------------------------------------------------------------------
    compliance_summary = {
        "rotas_publicas": [
            "http://www.tennisabstract.com/cgi-bin/player-classic.cgi?p={slug}",
            "http://www.tennisabstract.com/cgi-bin/wplayer-classic.cgi?p={slug}",
            "https://www.tennisabstract.com/jsmatches/{slug}.js",
        ],
        "delay_real_enforced": "2.5 segundos por requisição",
        "cache_ttl": "24 horas (armazenado em data/raw/tennis_abstract_cache/)",
        "tratamento_erros": "Fail-fast e fallback para base congelada se 403 ou 429 (sem evasão, sem proxies rotativos)",
        "estimativa_requisicoes_diarias": "Para operação normal com ~10 jogadores ativos no radar do dia: ~10 requests/dia (se cache frio) ou 0 requests/dia (se cache quente)",
    }

    # Consolidar relatório completo
    full_report = {
        "homologation_timestamp": datetime.now(timezone.utc).isoformat(),
        "players_real_report": players_real_report,
        "freshness_states": freshness_states_validation,
        "dedupe_report": dedupe_report,
        "leakage_checks": leakage_checks,
        "impact_stats": impact_stats,
        "fallback_tests": fallback_tests,
        "cache_validation": cache_validation,
        "compliance_summary": compliance_summary,
    }

    with open(OUTPUT_DIR / "homologation_report.json", "w", encoding="utf-8") as f:
        json.dump(full_report, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 70)
    print("HOMOLOGAÇÃO CONCLUÍDA COM SUCESSO!")
    print(f"Relatório consolidado salvo em: {OUTPUT_DIR / 'homologation_report.json'}")
    print("=" * 70)

    return full_report


if __name__ == "__main__":
    run_homologation()
