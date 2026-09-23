"""Testes da Fase 10 (item 15): edge insuficiente/suficiente, amostra baixa,
restricao ativa, staleness alta, Grass, probabilidade extrema, linha
ausente, mercado nao aprovado, odds invalidas, repeticao da mesma
observacao, explicacao da decisao."""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.decision import build
from src.decision import config as cfg
from src.decision import rules
from src.decision import sample_quality as sq
from src.decision import staleness_policy as stale


def _base_row(**overrides) -> dict:
    row = {
        "bookmaker": "Betano",
        "match_id": "FUTURE:ATP:0",
        "tour": "ATP",
        "market": "aces_player",
        "player": "Sebastian Baez",
        "side": "over",
        "line": 8.5,
        "decimal_odds": 5.0,
        "collected_at": "2026-09-22T14:00:00+00:00",
        "matched": True,
        "match_reason": "",
        "operational_probability": 0.65,
        "fair_odds": 1.538,
        "sample_bucket_career": "large_50_plus",
        "restricted": False,
        "restricted_motivo": None,
        "extreme_probability": False,
        "is_candidate": True,
        "implied_probability": 0.20,
        "model_edge": 0.10,
        "status": "ATINGE_EDGE_10",
        "historical_data_cutoff": "2026-05-25",
        "data_staleness_days": 10,
        "staleness_warning": "Base historica atualizada ate 2026-05-25 -- defasagem de 10 dias.",
        "player_id": "ATP-999001",
        "surface_ctx": "Hard",
        "method_selected": "platt",
        "cold_start": False,
        "insufficient_history": False,
        "calibrator_insufficient_sample": False,
        "resolution_method_player": "exact",
        "resolution_method_opponent": "exact",
        "prior_matches_career": 100,
        "prior_service_points_career": 500,
        "prior_return_points_career": 500,
        "surface_prior_matches": 20,
        "player_cold_start": False,
        "player_surface_cold_start": False,
    }
    row.update(overrides)
    return row


class TestSampleQuality(unittest.TestCase):
    def test_high_requires_all_four_signals(self):
        q = sq.classify_sample_quality(100, 500, 500, 20, feature_consistent=True)
        self.assertEqual(q, cfg.SAMPLE_QUALITY_HIGH)

    def test_medium_when_below_high_but_above_medium_thresholds(self):
        q = sq.classify_sample_quality(15, 100, 100, 2, feature_consistent=True)
        self.assertEqual(q, cfg.SAMPLE_QUALITY_MEDIUM)

    def test_low_when_below_medium_thresholds(self):
        q = sq.classify_sample_quality(3, 20, 20, 0, feature_consistent=True)
        self.assertEqual(q, cfg.SAMPLE_QUALITY_LOW)

    def test_low_when_missing_data_never_treated_as_ok(self):
        q = sq.classify_sample_quality(100, float("nan"), 500, 20, feature_consistent=True)
        self.assertEqual(q, cfg.SAMPLE_QUALITY_LOW)

    def test_low_when_feature_inconsistent_even_with_high_counts(self):
        q = sq.classify_sample_quality(100, 500, 500, 20, feature_consistent=False)
        self.assertEqual(q, cfg.SAMPLE_QUALITY_LOW)


class TestStalenessPolicy(unittest.TestCase):
    def test_atual_bucket(self):
        self.assertEqual(stale.classify_staleness(5), cfg.STALENESS_ATUAL)

    def test_moderado_bucket(self):
        self.assertEqual(stale.classify_staleness(60), cfg.STALENESS_MODERADO)

    def test_muito_defasado_bucket(self):
        self.assertEqual(stale.classify_staleness(120), cfg.STALENESS_MUITO_DEFASADO)

    def test_missing_staleness_treated_as_worst_case(self):
        self.assertEqual(stale.classify_staleness(None), cfg.STALENESS_MUITO_DEFASADO)

    def test_blocks_candidato_forte_only_when_muito_defasado(self):
        self.assertTrue(stale.blocks_candidato_forte(cfg.STALENESS_MUITO_DEFASADO))
        self.assertFalse(stale.blocks_candidato_forte(cfg.STALENESS_MODERADO))
        self.assertFalse(stale.blocks_candidato_forte(cfg.STALENESS_ATUAL))


class TestEdgeInsufficient(unittest.TestCase):
    def test_edge_below_market_floor_is_observar(self):
        row = _base_row(status="ABAIXO_DO_LIMITE", model_edge=-0.01)
        result = rules.evaluate_opportunity(row)
        self.assertEqual(result["classification"], cfg.STATE_OBSERVAR)


class TestEdgeSufficient(unittest.TestCase):
    def test_strong_edge_with_high_sample_is_candidato_forte(self):
        row = _base_row(status="ATINGE_EDGE_10", model_edge=0.12)
        result = rules.evaluate_opportunity(row)
        self.assertEqual(result["classification"], cfg.STATE_CANDIDATO_FORTE)

    def test_edge_exactly_at_market_floor_is_candidato_fraco(self):
        # ATP aces_player floor = ATINGE_EDGE_3 (config.MARKET_MIN_EDGE_LABEL)
        row = _base_row(status="ATINGE_EDGE_3", model_edge=0.035)
        result = rules.evaluate_opportunity(row)
        self.assertEqual(result["classification"], cfg.STATE_CANDIDATO_FRACO)

    def test_mid_edge_with_medium_sample_is_candidato_fraco(self):
        row = _base_row(
            status="ATINGE_EDGE_5", model_edge=0.055,
            prior_matches_career=15, prior_service_points_career=100,
            prior_return_points_career=100, surface_prior_matches=2,
        )
        result = rules.evaluate_opportunity(row)
        self.assertEqual(result["metrics"]["sample_quality"], cfg.SAMPLE_QUALITY_MEDIUM)
        self.assertEqual(result["classification"], cfg.STATE_CANDIDATO_FRACO)

    def test_mid_edge_with_high_sample_is_candidato(self):
        row = _base_row(status="ATINGE_EDGE_5", model_edge=0.055)
        result = rules.evaluate_opportunity(row)
        self.assertEqual(result["classification"], cfg.STATE_CANDIDATO)

    def test_higher_edge_never_downgrades_relative_to_lower_edge(self):
        weaker = rules.evaluate_opportunity(_base_row(status="ATINGE_EDGE_3", model_edge=0.035))
        stronger = rules.evaluate_opportunity(_base_row(status="ATINGE_EDGE_10", model_edge=0.12))
        rank = {s: i for i, s in enumerate(cfg.STATES_ORDER)}
        self.assertGreaterEqual(rank[stronger["classification"]], rank[weaker["classification"]])


class TestLowSample(unittest.TestCase):
    def test_low_sample_quality_is_gated_to_descartar(self):
        row = _base_row(prior_matches_career=3, prior_service_points_career=10, prior_return_points_career=10)
        result = rules.evaluate_opportunity(row)
        self.assertEqual(result["classification"], cfg.STATE_DESCARTAR)
        self.assertTrue(any("qualidade de amostra = LOW" in r for r in result["reasons"]))


class TestRestrictionActive(unittest.TestCase):
    def test_restricted_prediction_is_descartar_even_with_positive_edge(self):
        row = _base_row(
            restricted=True, restricted_motivo="ECE piora em Grass apos Platt",
            status="ATINGE_EDGE_10", model_edge=0.15,
        )
        result = rules.evaluate_opportunity(row)
        self.assertEqual(result["classification"], cfg.STATE_DESCARTAR)
        self.assertTrue(any("ECE piora em Grass" in r for r in result["reasons"]))


class TestGrassRestrictionPreserved(unittest.TestCase):
    def test_atp_aces_player_grass_restriction_still_blocks(self):
        # item 7: a restricao ATP aces_player/Grass herdada da Fase 7 nunca
        # e removida automaticamente por esta fase.
        row = _base_row(
            tour="ATP", market="aces_player", surface_ctx="Grass",
            restricted=True, restricted_motivo="ATP aces_player em Grass -- USAR COM RESTRICAO (Fase 6.1)",
        )
        result = rules.evaluate_opportunity(row)
        self.assertEqual(result["classification"], cfg.STATE_DESCARTAR)


class TestStalenessHigh(unittest.TestCase):
    def test_candidato_forte_capped_when_staleness_muito_defasado(self):
        row = _base_row(status="ATINGE_EDGE_10", model_edge=0.15, data_staleness_days=120)
        result = rules.evaluate_opportunity(row)
        self.assertEqual(result["classification"], cfg.STATE_CANDIDATO)
        self.assertTrue(result["flags"]["candidato_forte_capped_by_staleness"])
        self.assertTrue(any("CANDIDATO_FORTE bloqueado" in a for a in result["alerts"]))

    def test_staleness_missing_is_gated_to_descartar(self):
        row = _base_row(data_staleness_days=float("nan"), historical_data_cutoff=None)
        result = rules.evaluate_opportunity(row)
        self.assertEqual(result["classification"], cfg.STATE_DESCARTAR)


class TestExtremeProbability(unittest.TestCase):
    def test_extreme_probability_never_auto_upgrades_or_downgrades(self):
        normal = rules.evaluate_opportunity(_base_row(extreme_probability=False))
        extreme = rules.evaluate_opportunity(_base_row(extreme_probability=True, operational_probability=0.95))
        self.assertEqual(normal["classification"], extreme["classification"])
        self.assertTrue(any("probabilidade extrema" in a for a in extreme["alerts"]))
        self.assertFalse(any("probabilidade extrema" in a for a in normal["alerts"]))


class TestLineMissing(unittest.TestCase):
    def test_unmatched_line_is_descartar(self):
        row = _base_row(
            matched=False, match_reason="linha 99.5 (over) nao existe na grade do modelo",
            operational_probability=float("nan"), status="ABAIXO_DO_LIMITE",
            resolution_method_player=None, resolution_method_opponent=None,
        )
        result = rules.evaluate_opportunity(row)
        self.assertEqual(result["classification"], cfg.STATE_DESCARTAR)
        self.assertTrue(any("nao casada" in r for r in result["reasons"]))


class TestMarketNotApproved(unittest.TestCase):
    def test_market_outside_scope_is_descartar(self):
        row = _base_row(market="total_games")
        result = rules.evaluate_opportunity(row)
        self.assertEqual(result["classification"], cfg.STATE_DESCARTAR)
        self.assertTrue(any("nao esta entre os aprovados" in r for r in result["reasons"]))


class TestInvalidOdds(unittest.TestCase):
    def test_odds_below_minimum_configured_is_descartar(self):
        row = _base_row(decimal_odds=1.05)
        result = rules.evaluate_opportunity(row)
        self.assertEqual(result["classification"], cfg.STATE_DESCARTAR)

    def test_nan_odds_is_descartar(self):
        row = _base_row(decimal_odds=float("nan"))
        result = rules.evaluate_opportunity(row)
        self.assertEqual(result["classification"], cfg.STATE_DESCARTAR)


class TestRepeatedObservation(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig_dir = cfg.PHASE10_DIR
        self._orig_path = cfg.OPPORTUNITIES_PATH
        cfg.PHASE10_DIR = tmp_dir
        cfg.OPPORTUNITIES_PATH = tmp_dir / "opportunities_evaluated.parquet"

    def tearDown(self):
        cfg.PHASE10_DIR = self._orig_dir
        cfg.OPPORTUNITIES_PATH = self._orig_path
        self._tmp.cleanup()

    def test_exact_resubmission_not_duplicated_in_ledger(self):
        row = _base_row()
        evaluated = build._evaluate_all(pd.DataFrame([row]))
        combined1 = build._append_opportunities(evaluated)
        combined2 = build._append_opportunities(evaluated)
        self.assertEqual(len(combined1), 1)
        self.assertEqual(len(combined2), 1)


class TestExplanation(unittest.TestCase):
    def test_explanation_always_has_motivos(self):
        result = rules.evaluate_opportunity(_base_row())
        text = rules.format_explanation(result)
        self.assertIn("Motivos:", text)
        self.assertTrue(text.startswith(result["classification"]))

    def test_explanation_includes_alertas_section_when_present(self):
        result = rules.evaluate_opportunity(_base_row(data_staleness_days=120, status="ATINGE_EDGE_10"))
        text = rules.format_explanation(result)
        self.assertIn("Alertas:", text)

    def test_no_forbidden_terms_in_any_explanation(self):
        cases = [
            _base_row(),
            _base_row(status="ABAIXO_DO_LIMITE", model_edge=-0.02),
            _base_row(restricted=True, restricted_motivo="x"),
            _base_row(market="total_games"),
        ]
        for row in cases:
            result = rules.evaluate_opportunity(row)
            text = rules.format_explanation(result).lower()
            for term in cfg.FORBIDDEN_TERMS:
                self.assertNotIn(term, text)

    def test_stake_policy_is_always_not_implemented(self):
        result = rules.evaluate_opportunity(_base_row())
        self.assertEqual(result["stake_policy"], cfg.STAKE_POLICY_NOT_IMPLEMENTED)


class TestBuildEndToEndWithRealData(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig = {
            "PHASE10_DIR": cfg.PHASE10_DIR,
            "OPPORTUNITIES_PATH": cfg.OPPORTUNITIES_PATH,
            "OPERATIONAL_RULES_PATH": cfg.OPERATIONAL_RULES_PATH,
            "CLASSIFICATION_SUMMARY_PATH": cfg.CLASSIFICATION_SUMMARY_PATH,
            "REJECTED_PATH": cfg.REJECTED_PATH,
            "PHASE10_SUMMARY_PATH": cfg.PHASE10_SUMMARY_PATH,
        }
        cfg.PHASE10_DIR = tmp_dir
        cfg.OPPORTUNITIES_PATH = tmp_dir / "opportunities_evaluated.parquet"
        cfg.OPERATIONAL_RULES_PATH = tmp_dir / "operational_rules.json"
        cfg.CLASSIFICATION_SUMMARY_PATH = tmp_dir / "classification_summary.csv"
        cfg.REJECTED_PATH = tmp_dir / "rejected_opportunities.csv"
        cfg.PHASE10_SUMMARY_PATH = tmp_dir / "phase10_summary.json"

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(cfg, k, v)
        self._tmp.cleanup()

    def test_run_against_real_phase8_phase9_outputs(self):
        if not cfg.PHASE9_COMPARISON_PATH.exists():
            self.skipTest("data/outputs/phase9/comparison_with_model.parquet nao existe nesta maquina")
        result = build.run()
        self.assertGreaterEqual(result["n_opportunities_evaluated_this_run"], 1)
        self.assertTrue(cfg.OPPORTUNITIES_PATH.exists())
        self.assertTrue(cfg.OPERATIONAL_RULES_PATH.exists())
        self.assertTrue(cfg.CLASSIFICATION_SUMMARY_PATH.exists())
        self.assertTrue(cfg.REJECTED_PATH.exists())

    def test_idempotent_run_produces_same_ledger_size(self):
        if not cfg.PHASE9_COMPARISON_PATH.exists():
            self.skipTest("data/outputs/phase9/comparison_with_model.parquet nao existe nesta maquina")
        r1 = build.run()
        r2 = build.run()
        self.assertEqual(r1["n_opportunities_total_ledger"], r2["n_opportunities_total_ledger"])


if __name__ == "__main__":
    unittest.main()
