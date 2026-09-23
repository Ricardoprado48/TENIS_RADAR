"""Testes de validacao da Fase 6 (item 11): probabilidades em [0,1],
Over+Under=1, monotonicidade das linhas, distribuicao consistente, nenhum
dado futuro usado, estabilidade da Negative Binomial, casos extremos."""

from __future__ import annotations

import unittest

import numpy as np

from src.probabilistic import config as cfg
from src.probabilistic import dependency as dep
from src.probabilistic import distributions as dist


class TestLineProbabilitiesBounds(unittest.TestCase):
    def test_probabilities_in_unit_interval(self):
        lam = np.array([0.5, 2.0, 6.3, 15.0, 40.0])
        for r in [None, 0.8, 2.5, 10.0]:
            probs = dist.line_probabilities(lam, r, 3.5)
            for key in ["p_over_poisson", "p_under_poisson"]:
                self.assertTrue(np.all(probs[key] >= 0.0))
                self.assertTrue(np.all(probs[key] <= 1.0))
            if r is not None:
                for key in ["p_over_negbin", "p_under_negbin"]:
                    self.assertTrue(np.all(probs[key] >= 0.0))
                    self.assertTrue(np.all(probs[key] <= 1.0))

    def test_over_plus_under_equals_one_no_push(self):
        lam = np.array([1.2, 4.4, 9.9])
        for r in [None, 1.5, 5.0]:
            for line in [0.5, 3.5, 7.5]:
                probs = dist.line_probabilities(lam, r, line)
                total_poisson = probs["p_over_poisson"] + probs["p_under_poisson"]
                np.testing.assert_allclose(total_poisson, 1.0, atol=1e-9)
                if r is not None:
                    total_nb = probs["p_over_negbin"] + probs["p_under_negbin"]
                    np.testing.assert_allclose(total_nb, 1.0, atol=1e-9)

    def test_negbin_nan_when_r_is_none(self):
        lam = np.array([2.0, 5.0])
        probs = dist.line_probabilities(lam, None, 2.5)
        self.assertTrue(np.all(np.isnan(probs["p_over_negbin"])))
        self.assertTrue(np.all(np.isnan(probs["p_under_negbin"])))


class TestMonotonicity(unittest.TestCase):
    def test_p_over_decreases_as_line_increases(self):
        lam = np.array([6.5])
        r = 2.3
        lines = [0.5, 1.5, 3.5, 5.5, 7.5, 9.5, 12.5, 20.5]
        p_poisson = [dist.line_probabilities(lam, r, l)["p_over_poisson"][0] for l in lines]
        p_negbin = [dist.line_probabilities(lam, r, l)["p_over_negbin"][0] for l in lines]
        self.assertTrue(all(a >= b - 1e-12 for a, b in zip(p_poisson, p_poisson[1:])))
        self.assertTrue(all(a >= b - 1e-12 for a, b in zip(p_negbin, p_negbin[1:])))


class TestLineGrid(unittest.TestCase):
    def test_grid_is_sorted_half_integers_and_bounded(self):
        lines = dist.generate_line_grid(6.2, 1.9)
        self.assertGreater(len(lines), 0)
        self.assertLessEqual(len(lines), cfg.MAX_LINES_PER_GROUP)
        self.assertEqual(lines, sorted(lines))
        for l in lines:
            self.assertAlmostEqual(l % 1, 0.5, places=9)

    def test_empty_grid_for_invalid_mean(self):
        self.assertEqual(dist.generate_line_grid(None, 1.0), [])
        self.assertEqual(dist.generate_line_grid(0.0, 1.0), [])
        self.assertEqual(dist.generate_line_grid(float("nan"), 1.0), [])

    def test_grid_falls_back_to_poisson_when_r_is_none(self):
        lines_nb = dist.generate_line_grid(5.0, 2.0)
        lines_poisson = dist.generate_line_grid(5.0, None)
        self.assertGreater(len(lines_nb), 0)
        self.assertGreater(len(lines_poisson), 0)
        # Negative Binomial tem cauda mais pesada -- a grade correspondente
        # nao deve ser mais estreita que a do Poisson para a mesma media.
        self.assertGreaterEqual(max(lines_nb), max(lines_poisson))


class TestLineDifficultyBucket(unittest.TestCase):
    def test_buckets_match_expected_regions(self):
        lam = np.array([5.0])
        r = 2.0
        var = lam[0] + (lam[0] ** 2) / r
        std = var ** 0.5
        far_below = float(lam[0] - 3 * std)
        near = float(lam[0])
        far_above = float(lam[0] + 3 * std)
        self.assertEqual(dist.line_difficulty_bucket(far_below, lam, r)[0], "muito_abaixo_da_media")
        self.assertEqual(dist.line_difficulty_bucket(near, lam, r)[0], "proxima_da_media")
        self.assertEqual(dist.line_difficulty_bucket(far_above, lam, r)[0], "muito_acima_da_media")


class TestExtremeCases(unittest.TestCase):
    def test_zero_lambda(self):
        probs = dist.line_probabilities(np.array([0.0]), 2.0, 0.5)
        self.assertAlmostEqual(probs["p_over_poisson"][0], 0.0, places=9)
        self.assertAlmostEqual(probs["p_over_negbin"][0], 0.0, places=9)

    def test_huge_lambda_stays_finite_and_bounded(self):
        probs = dist.line_probabilities(np.array([500.0]), 3.0, 6.5)
        self.assertTrue(np.isfinite(probs["p_over_poisson"][0]))
        self.assertTrue(np.isfinite(probs["p_over_negbin"][0]))
        self.assertAlmostEqual(probs["p_over_poisson"][0], 1.0, places=4)
        self.assertAlmostEqual(probs["p_over_negbin"][0], 1.0, places=3)

    def test_tiny_dispersion_r_stays_stable(self):
        probs = dist.line_probabilities(np.array([4.0]), 0.01, 3.5)
        self.assertTrue(np.isfinite(probs["p_over_negbin"][0]))
        self.assertGreaterEqual(probs["p_over_negbin"][0], 0.0)
        self.assertLessEqual(probs["p_over_negbin"][0], 1.0)


class TestIndependentSum(unittest.TestCase):
    def test_variance_adds_under_independence(self):
        lam_a = np.array([4.0])
        lam_b = np.array([3.0])
        r_a, r_b = 2.0, 5.0
        lam_total, r_indep = dep.independent_sum_r(lam_a, r_a, lam_b, r_b)
        var_a = lam_a[0] + lam_a[0] ** 2 / r_a
        var_b = lam_b[0] + lam_b[0] ** 2 / r_b
        expected_var_total = var_a + var_b
        implied_var_total = lam_total[0] + lam_total[0] ** 2 / r_indep[0]
        self.assertAlmostEqual(lam_total[0], 7.0, places=9)
        self.assertAlmostEqual(implied_var_total, expected_var_total, places=6)

    def test_returns_nan_when_variance_not_overdispersed(self):
        # Poisson puro (var == media) em ambos os jogadores -> soma tambem
        # Poisson, sem r finito bem definido (comportamento esperado, nao um
        # bug: ver docstring de fit_negbin_r em src/baselines/count_dist.py).
        lam_a = np.array([4.0])
        lam_b = np.array([3.0])
        lam_total, r_indep = dep.independent_sum_r(lam_a, None, lam_b, None)
        self.assertTrue(np.isnan(r_indep[0]))


class TestNoFutureFoldLeakage(unittest.TestCase):
    def test_fold_test_windows_are_disjoint_and_chronological(self):
        from src.baselines.config import FOLDS as BASELINE_FOLDS

        # a Fase 6 reaproveita literalmente os folds da Fase 4 (nunca
        # redefine limites de data por conta propria).
        self.assertEqual([f["name"] for f in BASELINE_FOLDS], cfg.FOLDS)
        ends = [f["test_end"] for f in BASELINE_FOLDS]
        starts = [f["test_start"] for f in BASELINE_FOLDS]
        for i in range(len(BASELINE_FOLDS) - 1):
            self.assertLess(ends[i], starts[i + 1])


if __name__ == "__main__":
    unittest.main()
