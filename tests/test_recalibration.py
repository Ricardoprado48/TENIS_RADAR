"""Testes de validacao da Fase 6.1 (item 12): probabilidades calibradas em
[0,1], monotonicidade, ausencia de leakage temporal, calibrador treinado so
com periodo anterior, reprodutibilidade, fallback seguro."""

from __future__ import annotations

import unittest

import numpy as np

from src.recalibration import config as cfg
from src.recalibration import methods as meth


def _synthetic_well_calibrated_raw(n=4000, seed=20260922):
    rng = np.random.default_rng(seed)
    true_p = rng.uniform(0.01, 0.99, size=n)
    # p_raw sistematicamente "achatado" em torno de 0.5 (mesmo padrao de
    # subconfianca observado na Fase 6) -- um calibrador de verdade deve
    # corrigir isso.
    p_raw = 0.5 + (true_p - 0.5) * 0.5
    y = (rng.uniform(size=n) < true_p).astype("float64")
    return p_raw, y


class TestCalibratedProbabilitiesBounds(unittest.TestCase):
    def test_platt_and_isotonic_in_unit_interval(self):
        p_raw, y = _synthetic_well_calibrated_raw()
        platt, status_p = meth.fit_calibrator("platt", p_raw, y)
        iso, status_i = meth.fit_calibrator("isotonic", p_raw, y)
        self.assertEqual(status_p, "platt")
        self.assertEqual(status_i, "isotonic")
        grid = np.linspace(0.01, 0.99, 200)
        for model in [platt, iso]:
            out = model.predict(grid)
            self.assertTrue(np.all(out >= 0.0))
            self.assertTrue(np.all(out <= 1.0))
            self.assertTrue(np.all(np.isfinite(out)))


class TestMonotonicity(unittest.TestCase):
    def test_calibrated_probability_nondecreasing_in_raw(self):
        p_raw, y = _synthetic_well_calibrated_raw()
        platt, _ = meth.fit_calibrator("platt", p_raw, y)
        iso, _ = meth.fit_calibrator("isotonic", p_raw, y)
        grid = np.sort(np.linspace(0.01, 0.99, 300))
        for model in [platt, iso]:
            out = model.predict(grid)
            self.assertTrue(np.all(np.diff(out) >= -1e-9))

    def test_line_ordering_preserved_after_calibration(self):
        # dentro da MESMA partida, p_raw ja e decrescente conforme a linha
        # aumenta (garantido na Fase 6) -- uma funcao de calibracao monotona
        # precisa preservar essa ordem.
        p_raw, y = _synthetic_well_calibrated_raw()
        platt, _ = meth.fit_calibrator("platt", p_raw, y)
        p_raw_lines = np.array([0.92, 0.81, 0.65, 0.40, 0.18, 0.05])
        calibrated = platt.predict(p_raw_lines)
        self.assertTrue(np.all(np.diff(calibrated) <= 1e-9))


class TestFallbackSafety(unittest.TestCase):
    def test_insufficient_sample_falls_back_to_raw(self):
        p_raw = np.array([0.3, 0.6, 0.4, 0.7])
        y = np.array([0.0, 1.0, 0.0, 1.0])
        model, status = meth.fit_calibrator("platt", p_raw, y, min_n=cfg.MIN_CALIBRATOR_TRAIN_N)
        self.assertIsInstance(model, meth.RawCalibrator)
        self.assertIn("amostra_insuficiente", status)
        np.testing.assert_array_equal(model.predict(p_raw), p_raw)

    def test_single_class_target_falls_back_to_raw(self):
        p_raw = np.linspace(0.1, 0.9, 600)
        y = np.zeros(600)  # nenhum evento positivo no periodo de treino
        platt_model, platt_status = meth.fit_calibrator("platt", p_raw, y)
        iso_model, iso_status = meth.fit_calibrator("isotonic", p_raw, y)
        self.assertIsInstance(platt_model, meth.RawCalibrator)
        self.assertIsInstance(iso_model, meth.RawCalibrator)
        self.assertIn("degenerado", platt_status)
        self.assertIn("degenerado", iso_status)

    def test_inverted_relationship_falls_back_to_raw_platt(self):
        # p_raw ALTO associado a y=0 e p_raw BAIXO associado a y=1 -- uma
        # relacao invertida nao deve virar um "calibrador" que so pioraria
        # as probabilidades (item 12: fallback seguro).
        rng = np.random.default_rng(1)
        n = 2000
        p_raw = rng.uniform(0.05, 0.95, size=n)
        y = (rng.uniform(size=n) < (1 - p_raw)).astype("float64")
        model, status = meth.fit_calibrator("platt", p_raw, y)
        self.assertIsInstance(model, meth.RawCalibrator)
        self.assertIn("degenerado", status)


class TestReproducibility(unittest.TestCase):
    def test_platt_and_isotonic_are_deterministic(self):
        p_raw, y = _synthetic_well_calibrated_raw()
        grid = np.linspace(0.05, 0.95, 50)
        platt_a, _ = meth.fit_calibrator("platt", p_raw, y)
        platt_b, _ = meth.fit_calibrator("platt", p_raw, y)
        np.testing.assert_allclose(platt_a.predict(grid), platt_b.predict(grid))
        iso_a, _ = meth.fit_calibrator("isotonic", p_raw, y)
        iso_b, _ = meth.fit_calibrator("isotonic", p_raw, y)
        np.testing.assert_allclose(iso_a.predict(grid), iso_b.predict(grid))


class TestNoTemporalLeakage(unittest.TestCase):
    def test_calibration_train_folds_never_include_the_evaluated_fold_or_the_future(self):
        fold_order = cfg.FOLDS
        for eval_fold, train_folds in cfg.CALIBRATION_TRAIN_FOLDS.items():
            eval_idx = fold_order.index(eval_fold)
            for tf in train_folds:
                self.assertNotEqual(tf, eval_fold, "calibrador nao pode treinar com o proprio fold avaliado")
                self.assertLess(fold_order.index(tf), eval_idx, "calibrador nao pode usar fold futuro")

    def test_fold_2024_has_no_prior_period_and_is_never_calibrated(self):
        self.assertNotIn("fold_2024", cfg.CALIBRATION_TRAIN_FOLDS)
        self.assertIn("fold_2024", cfg.NO_PRIOR_PERIOD_FOLDS)

    def test_fold_2026_calibrator_uses_expanding_window(self):
        self.assertEqual(set(cfg.CALIBRATION_TRAIN_FOLDS["fold_2026"]), {"fold_2024", "fold_2025"})


if __name__ == "__main__":
    unittest.main()
