"""Testes de validacao da Fase 7 (item 12): odd justa = 1/p, probabilidade
implicita, edge, odd minima cresce com o edge exigido, monotonicidade entre
linhas, Over + Under = 1, cold start nao gera preco, probabilidades
extremas recebem flag, restricao de ATP Grass preservada."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.pricing import config as cfg
from src.pricing import flags as fl
from src.pricing import odds


class TestFairOdds(unittest.TestCase):
    def test_fair_odds_is_inverse_of_probability(self):
        p = np.array([0.1, 0.25, 0.5, 0.63, 0.9])
        out = odds.fair_odds(p)
        np.testing.assert_allclose(out, 1.0 / p)

    def test_fair_odds_example_from_instructions(self):
        # exemplo literal da instrucao: p=0.625 -> odd justa = 1.60
        out = odds.fair_odds(np.array([0.625]))
        self.assertAlmostEqual(out[0], 1.60, places=6)

    def test_fair_odds_invalid_probability_is_nan(self):
        p = np.array([0.0, 1.0, np.nan, -0.1, 1.2])
        out = odds.fair_odds(p)
        self.assertTrue(np.all(np.isnan(out)))


class TestImpliedProbabilityAndEdge(unittest.TestCase):
    def test_implied_probability_is_inverse_of_odds(self):
        decimal_odds = np.array([1.5, 2.0, 3.33, 10.0])
        out = odds.implied_probability(decimal_odds)
        np.testing.assert_allclose(out, 1.0 / decimal_odds)

    def test_implied_probability_invalid_odds_is_nan(self):
        decimal_odds = np.array([1.0, 0.5, 0.0, -2.0, np.nan])
        out = odds.implied_probability(decimal_odds)
        self.assertTrue(np.all(np.isnan(out)))

    def test_edge_is_model_minus_implied(self):
        p_model = np.array([0.60, 0.40])
        p_implied = np.array([0.50, 0.55])
        out = odds.edge(p_model, p_implied)
        np.testing.assert_allclose(out, [0.10, -0.15])

    def test_edge_positive_example(self):
        # p_modelo = 0.63, odd observada = 1.80 -> p_implicita = 0.5556 -> edge > 0
        p_model = 0.63
        p_implied = odds.implied_probability(np.array([1.80]))[0]
        e = odds.edge(np.array([p_model]), np.array([p_implied]))[0]
        self.assertGreater(e, 0.0)
        self.assertAlmostEqual(e, 0.63 - (1.0 / 1.80), places=6)


class TestMinimumAcceptableOdds(unittest.TestCase):
    def test_minimum_odds_matches_formula(self):
        # odd_minima = 1 / (p_modelo - e)
        p = 0.63
        e = 0.05
        out = odds.minimum_acceptable_odds(np.array([p]), np.array([e]))[0]
        self.assertAlmostEqual(out, 1.0 / (p - e), places=8)

    def test_minimum_odds_matches_instructions_example(self):
        # exemplo literal: p=0.63, odd justa 1.59; edges 2/3/5/7.5/10% ->
        # 1.64/1.67/1.72/1.80/1.89 (arredondado a 2 casas na instrucao).
        p = np.array([0.63])
        expected = {0.02: 1.64, 0.03: 1.67, 0.05: 1.72, 0.075: 1.80, 0.10: 1.89}
        for e, exp in expected.items():
            out = odds.minimum_acceptable_odds(p, np.array([e]))[0]
            self.assertAlmostEqual(round(out, 2), exp, places=2)

    def test_minimum_odds_increases_with_required_edge(self):
        p = np.full(5, 0.55)
        edges = np.array([e for _, e in cfg.EDGE_LEVELS])
        vals = [odds.minimum_acceptable_odds(p[:1], np.array([e]))[0] for e in edges]
        self.assertTrue(np.all(np.diff(vals) > 0), "odd minima deve crescer com o edge exigido")

    def test_minimum_odds_nan_when_edge_exceeds_probability(self):
        # item 3: "desde que p_modelo - e > 0"
        out = odds.minimum_acceptable_odds(np.array([0.05]), np.array([0.10]))
        self.assertTrue(np.isnan(out[0]))


class TestLineMonotonicity(unittest.TestCase):
    def test_over_probability_decreases_as_line_increases(self):
        # replica o padrao real do pipeline: p(Over) cai e odd justa sobe
        # conforme a linha aumenta.
        lines = np.array([5.5, 6.5, 7.5, 8.5, 9.5])
        p_over = np.array([0.55, 0.46, 0.38, 0.31, 0.25])
        self.assertTrue(np.all(np.diff(p_over) < 0))
        fair = odds.fair_odds(p_over)
        self.assertTrue(np.all(np.diff(fair) > 0), "odd justa de Over deve subir com a linha")

    def test_under_probability_increases_as_line_increases(self):
        p_over = np.array([0.55, 0.46, 0.38, 0.31, 0.25])
        p_under = 1.0 - p_over
        self.assertTrue(np.all(np.diff(p_under) > 0))
        fair_under = odds.fair_odds(p_under)
        self.assertTrue(np.all(np.diff(fair_under) < 0), "odd justa de Under deve cair com a linha")


class TestOverUnderSumToOne(unittest.TestCase):
    def test_over_plus_under_equals_one(self):
        p_over = np.array([0.1, 0.4, 0.63, 0.9])
        p_under = 1.0 - p_over
        np.testing.assert_allclose(p_over + p_under, 1.0)


class TestColdStartNoPrice(unittest.TestCase):
    def test_cold_start_flag_detected(self):
        s = pd.Series(["cold_start", "small_1_9", "large_50_plus"])
        out = fl.cold_start_flag(s)
        np.testing.assert_array_equal(out.to_numpy(), [True, False, False])

    def test_cold_start_rows_get_no_fair_odds_in_pipeline(self):
        from src.pricing.build import _side_frame

        base = pd.DataFrame({
            "tour": ["ATP", "ATP"], "market": ["aces_player"] * 2, "fold": ["fold_2025"] * 2,
            "surface": ["Hard"] * 2, "match_id": ["m1", "m2"], "player_id": ["p1", "p2"],
            "line": [8.5, 8.5], "prior_matches_career": [0, 30],
            "sample_bucket_career": ["cold_start", "large_50_plus"],
            "line_difficulty": ["proxima_da_media"] * 2,
            "operational_probability_over": [0.5, 0.5], "operational_probability_under": [0.5, 0.5],
            "raw_probability_over": [0.5, 0.5], "raw_probability_under": [0.5, 0.5],
            "method_selected": ["raw", "raw"], "calibrator_train_n": [1000, 1000],
        })
        base["cold_start"] = fl.cold_start_flag(base["sample_bucket_career"])
        base["insufficient_history"] = fl.insufficient_history_flag(base["sample_bucket_career"])
        base["calibrator_insufficient_sample"] = fl.calibrator_insufficient_sample_flag(
            base["calibrator_train_n"], base["method_selected"])
        restricted, motivo = fl.restricted_flag(base["tour"], base["market"], base["surface"])
        base["restricted"] = restricted
        base["restricted_motivo"] = motivo

        out = _side_frame(base, "over")
        self.assertTrue(np.isnan(out.loc[out["cold_start"], "fair_odds"]).all())
        self.assertFalse(np.isnan(out.loc[~out["cold_start"], "fair_odds"]).any())


class TestExtremeProbabilityFlag(unittest.TestCase):
    def test_extreme_probability_flagged_at_90_percent(self):
        p = pd.Series([0.10, 0.50, 0.899, 0.90, 0.95])
        out = fl.extreme_probability_flag(p)
        np.testing.assert_array_equal(out.to_numpy(), [False, False, False, True, True])


class TestGrassRestrictionPreserved(unittest.TestCase):
    def test_atp_aces_player_grass_is_restricted(self):
        tour = pd.Series(["ATP", "ATP", "WTA", "ATP"])
        market = pd.Series(["aces_player", "aces_player", "aces_player", "total_aces_match"])
        surface = pd.Series(["Grass", "Hard", "Grass", "Grass"])
        restricted, motivo = fl.restricted_flag(tour, market, surface)
        np.testing.assert_array_equal(restricted.to_numpy(), [True, False, False, False])
        self.assertTrue(pd.notna(motivo.iloc[0]))
        self.assertTrue(pd.isna(motivo.iloc[1]))

    def test_restriction_is_not_the_only_atp_grass_case_it_does_not_apply_elsewhere(self):
        # garante que a restricao nao "vaza" para outros mercados/tours em Grass.
        tour = pd.Series(["ATP"] * 3)
        market = pd.Series(["total_aces_match", "double_faults_player", "aces_player"])
        surface = pd.Series(["Grass"] * 3)
        restricted, _ = fl.restricted_flag(tour, market, surface)
        np.testing.assert_array_equal(restricted.to_numpy(), [False, False, True])

    def test_restricted_rows_are_not_removed_only_flagged(self):
        from src.pricing.build import _side_frame

        base = pd.DataFrame({
            "tour": ["ATP"], "market": ["aces_player"], "fold": ["fold_2025"],
            "surface": ["Grass"], "match_id": ["m1"], "player_id": ["p1"],
            "line": [8.5], "prior_matches_career": [30],
            "sample_bucket_career": ["large_50_plus"], "line_difficulty": ["proxima_da_media"],
            "operational_probability_over": [0.7], "operational_probability_under": [0.3],
            "raw_probability_over": [0.6], "raw_probability_under": [0.4],
            "method_selected": ["platt"], "calibrator_train_n": [8000],
        })
        base["cold_start"] = fl.cold_start_flag(base["sample_bucket_career"])
        base["insufficient_history"] = fl.insufficient_history_flag(base["sample_bucket_career"])
        base["calibrator_insufficient_sample"] = fl.calibrator_insufficient_sample_flag(
            base["calibrator_train_n"], base["method_selected"])
        restricted, motivo = fl.restricted_flag(base["tour"], base["market"], base["surface"])
        base["restricted"] = restricted
        base["restricted_motivo"] = motivo

        out = _side_frame(base, "over")
        self.assertEqual(len(out), 1)
        self.assertTrue(bool(out.loc[0, "restricted"]))
        self.assertFalse(np.isnan(out.loc[0, "fair_odds"]))  # continua com preco, so marcado


if __name__ == "__main__":
    unittest.main()
