"""Testes da Fase 11 (item 20): registro imutavel, tentativa de sobrescrever
previsao, multiplos snapshots de odds, settlement, void, unresolved,
retirement, CLV, paper test flat, thresholds, classificacao, versionamento,
ausencia de leakage temporal, calculo das metricas."""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.forward import build
from src.forward import clv
from src.forward import config as cfg
from src.forward import ids
from src.forward import metrics
from src.forward import odds_snapshots as snaps
from src.forward import paper_test as pt
from src.forward import predictions as preds
from src.forward import results as res
from src.forward import settlement as settle
from src.forward import versioning


def _base_opportunity(**overrides) -> dict:
    row = {
        "bookmaker": "Betano",
        "match_id": "FUTURE:ATP:0",
        "tour": "ATP",
        "tournament": "Chengdu Open",
        "market": "aces_player",
        "player": "Sebastian Baez",
        "opponent": "Jenson Brooksby",
        "side": "over",
        "line": 5.5,
        "decimal_odds": 3.95,
        "collected_at": "2026-09-22T14:00:00+00:00",
        "operational_probability": 0.65,
        "fair_odds": 1.538,
        "odd_minima_2pct": 1.45, "odd_minima_3pct": 1.47, "odd_minima_5pct": 1.52,
        "odd_minima_7_5pct": 1.58, "odd_minima_10pct": 1.65,
        "implied_probability": 0.253,
        "model_edge": 0.10,
        "status": "ATINGE_EDGE_10",
        "classification": "CANDIDATO",
        "reasons": "edge = +10.0 p.p. | amostra = HIGH | calibracao aprovada | hard court",
        "alerts": "",
        "explanation": "CANDIDATO\n\nMotivos:\n- edge = +10.0 p.p.",
        "sample_quality": "HIGH",
        "method_selected": "platt",
        "restricted": False,
        "restricted_motivo": None,
        "extreme_probability": False,
        "staleness_bucket": "MUITO_DEFASADO",
        "stake_policy": "NOT_IMPLEMENTED",
        "surface_ctx": "Hard",
    }
    row.update(overrides)
    return row


def _use_temp_dirs(testcase: unittest.TestCase) -> None:
    tmp = tempfile.TemporaryDirectory()
    testcase.addCleanup(tmp.cleanup)
    tmp_dir = Path(tmp.name)

    attrs = [
        "PHASE11_DIR", "FORWARD_PREDICTIONS_PATH", "ODDS_SNAPSHOTS_PATH",
        "RESULTS_PATH", "SETTLEMENTS_PATH", "FORWARD_METRICS_PATH",
        "PAPER_TEST_PATH", "CLV_ANALYSIS_PATH", "PHASE11_SUMMARY_PATH",
    ]
    original = {a: getattr(cfg, a) for a in attrs}
    testcase.addCleanup(lambda: [setattr(cfg, a, v) for a, v in original.items()])

    cfg.PHASE11_DIR = tmp_dir
    cfg.FORWARD_PREDICTIONS_PATH = tmp_dir / "forward_predictions.parquet"
    cfg.ODDS_SNAPSHOTS_PATH = tmp_dir / "odds_snapshots.parquet"
    cfg.RESULTS_PATH = tmp_dir / "results.parquet"
    cfg.SETTLEMENTS_PATH = tmp_dir / "settlements.parquet"
    cfg.FORWARD_METRICS_PATH = tmp_dir / "forward_metrics.parquet"
    cfg.PAPER_TEST_PATH = tmp_dir / "paper_test.parquet"
    cfg.CLV_ANALYSIS_PATH = tmp_dir / "clv_analysis.parquet"
    cfg.PHASE11_SUMMARY_PATH = tmp_dir / "phase11_summary.json"


class TestImmutableRegistration(unittest.TestCase):
    def setUp(self):
        _use_temp_dirs(self)

    def test_register_creates_frozen_row(self):
        df = pd.DataFrame([_base_opportunity()])
        result = preds.register_predictions(df)
        self.assertEqual(len(result["added"]), 1)
        self.assertTrue(cfg.FORWARD_PREDICTIONS_PATH.exists())
        ledger = pd.read_parquet(cfg.FORWARD_PREDICTIONS_PATH)
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger.iloc[0]["classification"], "CANDIDATO")

    def test_identical_resubmission_is_noop(self):
        df = pd.DataFrame([_base_opportunity()])
        preds.register_predictions(df)
        result2 = preds.register_predictions(df)
        self.assertEqual(len(result2["added"]), 0)
        self.assertEqual(len(result2["skipped_duplicates"]), 1)
        ledger = pd.read_parquet(cfg.FORWARD_PREDICTIONS_PATH)
        self.assertEqual(len(ledger), 1)

    def test_overwrite_attempt_with_different_probability_is_rejected(self):
        preds.register_predictions(pd.DataFrame([_base_opportunity()]))
        changed = pd.DataFrame([_base_opportunity(operational_probability=0.80)])
        result = preds.register_predictions(changed)
        self.assertEqual(len(result["added"]), 0)
        self.assertEqual(len(result["rejected_overwrite_attempts"]), 1)
        ledger = pd.read_parquet(cfg.FORWARD_PREDICTIONS_PATH)
        self.assertEqual(len(ledger), 1)
        self.assertAlmostEqual(ledger.iloc[0]["operational_probability"], 0.65)

    def test_overwrite_attempt_with_different_odds_is_rejected(self):
        preds.register_predictions(pd.DataFrame([_base_opportunity()]))
        changed = pd.DataFrame([_base_opportunity(decimal_odds=10.0)])
        result = preds.register_predictions(changed)
        self.assertEqual(len(result["rejected_overwrite_attempts"]), 1)

    def test_different_line_produces_a_distinct_prediction(self):
        preds.register_predictions(pd.DataFrame([_base_opportunity()]))
        other_line = pd.DataFrame([_base_opportunity(line=6.5)])
        result = preds.register_predictions(other_line)
        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(len(result["rejected_overwrite_attempts"]), 0)
        ledger = pd.read_parquet(cfg.FORWARD_PREDICTIONS_PATH)
        self.assertEqual(len(ledger), 2)


class TestVersioning(unittest.TestCase):
    def test_version_stamp_has_all_required_fields(self):
        stamp = versioning.current_version_stamp("ATP")
        for field in [
            "forward_version_id", "features_version", "calibration_version",
            "rules_version", "git_commit", "historical_data_cutoff", "data_staleness_days",
        ]:
            self.assertIn(field, stamp)
        self.assertEqual(stamp["forward_version_id"], cfg.FORWARD_VERSION_ID)

    def test_git_commit_never_raises_even_without_repo(self):
        commit = versioning.current_git_commit()
        self.assertTrue(commit is None or isinstance(commit, str))


class TestOddsSnapshots(unittest.TestCase):
    def setUp(self):
        _use_temp_dirs(self)

    def test_multiple_snapshots_preserved_and_aggregated(self):
        pid = "PRED_test123"
        snaps.record_snapshot(pid, "Betano", 1.72, "2026-09-22T10:00:00+00:00")
        snaps.record_snapshot(pid, "Betano", 1.80, "2026-09-22T14:00:00+00:00")
        snaps.record_snapshot(pid, "Betano", 1.76, "2026-09-22T17:30:00+00:00")

        all_snaps = pd.read_parquet(cfg.ODDS_SNAPSHOTS_PATH)
        self.assertEqual(len(all_snaps), 3)

        summary = snaps.summarize_odds_movement()
        row = summary[summary["prediction_id"] == pid].iloc[0]
        self.assertEqual(row["first_observed_odds"], 1.72)
        self.assertEqual(row["last_observed_odds"], 1.76)
        self.assertEqual(row["best_observed_odds"], 1.80)

    def test_closing_odds_uses_match_start_cutoff(self):
        pid = "PRED_test456"
        snaps.record_snapshot(pid, "Betano", 1.70, "2026-09-22T10:00:00+00:00")
        snaps.record_snapshot(pid, "Betano", 1.90, "2026-09-22T20:00:00+00:00")  # depois do inicio

        summary = snaps.summarize_odds_movement(match_started_at="2026-09-22T15:00:00+00:00")
        row = summary[summary["prediction_id"] == pid].iloc[0]
        self.assertEqual(row["closing_odds_observed"], 1.70)
        self.assertEqual(row["last_observed_odds"], 1.90)

    def test_exact_resubmission_of_same_snapshot_not_duplicated(self):
        pid = "PRED_dup"
        snaps.record_snapshot(pid, "Betano", 1.72, "2026-09-22T10:00:00+00:00")
        snaps.record_snapshot(pid, "Betano", 1.72, "2026-09-22T10:00:00+00:00")
        self.assertEqual(len(pd.read_parquet(cfg.ODDS_SNAPSHOTS_PATH)), 1)


class TestResultsAndSettlement(unittest.TestCase):
    def setUp(self):
        _use_temp_dirs(self)
        self.prediction = {
            "prediction_id": "PRED_abc", "tour": "ATP", "match_id": "FUTURE:ATP:0",
            "market": "aces_player", "player": "Sebastian Baez", "line": 5.5, "side": "over",
        }

    def test_win_when_over_side_and_actual_above_line(self):
        result = {"tour": "ATP", "match_id": "FUTURE:ATP:0", "match_status": "completed",
                  "player_a": "Sebastian Baez", "player_b": "Jenson Brooksby",
                  "aces_player_a": 8, "aces_player_b": 4}
        outcome = settle.settle_prediction(self.prediction, result)
        self.assertEqual(outcome["settlement"], cfg.SETTLEMENT_WIN)

    def test_loss_when_over_side_and_actual_below_line(self):
        result = {"tour": "ATP", "match_id": "FUTURE:ATP:0", "match_status": "completed",
                  "player_a": "Sebastian Baez", "player_b": "Jenson Brooksby",
                  "aces_player_a": 3, "aces_player_b": 4}
        outcome = settle.settle_prediction(self.prediction, result)
        self.assertEqual(outcome["settlement"], cfg.SETTLEMENT_LOSS)

    def test_void_on_exact_push(self):
        pred = dict(self.prediction, line=5.0)
        result = {"tour": "ATP", "match_id": "FUTURE:ATP:0", "match_status": "completed",
                  "player_a": "Sebastian Baez", "player_b": "Jenson Brooksby",
                  "aces_player_a": 5, "aces_player_b": 4}
        outcome = settle.settle_prediction(pred, result)
        self.assertEqual(outcome["settlement"], cfg.SETTLEMENT_VOID)

    def test_unresolved_when_no_result_recorded(self):
        outcome = settle.settle_prediction(self.prediction, None)
        self.assertEqual(outcome["settlement"], cfg.SETTLEMENT_UNRESOLVED)

    def test_retirement_marks_bookmaker_rule_required_not_invented(self):
        result = {"tour": "ATP", "match_id": "FUTURE:ATP:0", "match_status": "retirement",
                  "player_a": "Sebastian Baez", "player_b": "Jenson Brooksby",
                  "aces_player_a": 8, "aces_player_b": 4}
        outcome = settle.settle_prediction(self.prediction, result)
        self.assertEqual(outcome["settlement"], cfg.SETTLEMENT_BOOKMAKER_RULE_REQUIRED)

    def test_walkover_marks_bookmaker_rule_required_not_invented(self):
        result = {"tour": "ATP", "match_id": "FUTURE:ATP:0", "match_status": "walkover",
                  "player_a": "Sebastian Baez", "player_b": "Jenson Brooksby"}
        outcome = settle.settle_prediction(self.prediction, result)
        self.assertEqual(outcome["settlement"], cfg.SETTLEMENT_BOOKMAKER_RULE_REQUIRED)

    def test_record_result_is_immutable(self):
        entry = {"tour": "ATP", "match_id": "FUTURE:ATP:0", "match_status": "completed",
                  "player_a": "Sebastian Baez", "player_b": "Jenson Brooksby",
                  "aces_player_a": 8, "aces_player_b": 4}
        r1 = res.record_result(entry)
        self.assertEqual(r1["status"], "recorded")
        r2 = res.record_result(entry)
        self.assertEqual(r2["status"], "already_recorded")
        changed = dict(entry, aces_player_a=99)
        r3 = res.record_result(changed)
        self.assertEqual(r3["status"], "rejected_overwrite_attempt")
        stored = res.load_results()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored.iloc[0]["aces_player_a"], 8)

    def test_settlement_terminal_state_is_immutable(self):
        predictions = pd.DataFrame([dict(self.prediction, operational_probability=0.65)])
        results = pd.DataFrame([{"tour": "ATP", "match_id": "FUTURE:ATP:0", "match_status": "completed",
                                  "player_a": "Sebastian Baez", "player_b": "Jenson Brooksby",
                                  "aces_player_a": 8, "aces_player_b": 4}])
        r1 = settle.settle_all(predictions, results)
        self.assertEqual(len(r1["new_events"]), 1)
        self.assertEqual(r1["new_events"].iloc[0]["settlement"], cfg.SETTLEMENT_WIN)

        bad_results = pd.DataFrame([{"tour": "ATP", "match_id": "FUTURE:ATP:0", "match_status": "completed",
                                      "player_a": "Sebastian Baez", "player_b": "Jenson Brooksby",
                                      "aces_player_a": 2, "aces_player_b": 4}])
        r2 = settle.settle_all(predictions, bad_results)
        self.assertEqual(len(r2["rejected_overwrite_attempts"]), 1)
        latest = settle.latest_settlements()
        self.assertEqual(latest.iloc[0]["settlement"], cfg.SETTLEMENT_WIN)

    def test_settlement_progresses_from_unresolved_to_terminal(self):
        predictions = pd.DataFrame([dict(self.prediction, operational_probability=0.65)])
        r1 = settle.settle_all(predictions, pd.DataFrame())
        self.assertEqual(r1["new_events"].iloc[0]["settlement"], cfg.SETTLEMENT_UNRESOLVED)

        results = pd.DataFrame([{"tour": "ATP", "match_id": "FUTURE:ATP:0", "match_status": "completed",
                                  "player_a": "Sebastian Baez", "player_b": "Jenson Brooksby",
                                  "aces_player_a": 8, "aces_player_b": 4}])
        r2 = settle.settle_all(predictions, results)
        self.assertEqual(len(r2["new_events"]), 1)
        self.assertEqual(r2["new_events"].iloc[0]["settlement"], cfg.SETTLEMENT_WIN)
        self.assertEqual(len(r2["rejected_overwrite_attempts"]), 0)


class TestCLV(unittest.TestCase):
    def setUp(self):
        _use_temp_dirs(self)

    def test_positive_clv_when_odds_used_better_than_closing(self):
        predictions = pd.DataFrame([{
            "prediction_id": "PRED_x", "tour": "ATP", "market": "aces_player",
            "player": "Sebastian Baez", "side": "over", "line": 5.5, "decimal_odds": 2.00,
        }])
        odds_movement = pd.DataFrame([{
            "prediction_id": "PRED_x", "n_snapshots": 2,
            "first_observed_odds": 2.00, "last_observed_odds": 1.80,
            "best_observed_odds": 2.00, "closing_odds_observed": 1.80,
            "closing_odds_note": "x",
        }])
        out = clv.compute_clv(predictions, odds_movement)
        self.assertEqual(len(out), 1)
        row = out.iloc[0]
        self.assertGreater(row["clv_pct"], 0)
        self.assertAlmostEqual(row["clv_pct"], (2.00 / 1.80 - 1) * 100, places=6)

    def test_never_interpreted_as_profit_proof_no_verdict_field(self):
        out = clv.compute_clv(
            pd.DataFrame([{"prediction_id": "P", "tour": "ATP", "market": "aces_player",
                            "player": "X", "side": "over", "line": 5.5, "decimal_odds": 2.0}]),
            pd.DataFrame([{"prediction_id": "P", "n_snapshots": 1, "first_observed_odds": 2.0,
                            "last_observed_odds": 2.0, "best_observed_odds": 2.0,
                            "closing_odds_observed": 1.9, "closing_odds_note": "x"}]),
        )
        self.assertNotIn("profitable", out.columns)
        self.assertNotIn("verdict", out.columns)


class TestPaperTest(unittest.TestCase):
    def _predictions(self):
        return pd.DataFrame([
            {"prediction_id": "P1", "market": "aces_player", "classification": "CANDIDATO", "decimal_odds": 2.0},
            {"prediction_id": "P2", "market": "aces_player", "classification": "CANDIDATO", "decimal_odds": 3.0},
            {"prediction_id": "P3", "market": "aces_player", "classification": "CANDIDATO", "decimal_odds": 1.5},
            {"prediction_id": "P4", "market": "aces_player", "classification": "DESCARTAR", "decimal_odds": 5.0},
        ])

    def _settlements(self):
        return pd.DataFrame([
            {"prediction_id": "P1", "settlement": cfg.SETTLEMENT_WIN, "settlement_reason": "", "settled_at": "2026-09-22T00:00:00Z"},
            {"prediction_id": "P2", "settlement": cfg.SETTLEMENT_LOSS, "settlement_reason": "", "settled_at": "2026-09-22T00:00:01Z"},
            {"prediction_id": "P3", "settlement": cfg.SETTLEMENT_VOID, "settlement_reason": "", "settled_at": "2026-09-22T00:00:02Z"},
            {"prediction_id": "P4", "settlement": cfg.SETTLEMENT_WIN, "settlement_reason": "", "settled_at": "2026-09-22T00:00:03Z"},
        ])

    def test_descartar_excluded_from_paper_test(self):
        out = pt.build_paper_test(self._predictions(), self._settlements())
        self.assertNotIn("P4", out["prediction_id"].tolist())

    def test_flat_stake_pnl_win_loss_void(self):
        out = pt.build_paper_test(self._predictions(), self._settlements())
        by_id = out.set_index("prediction_id")
        self.assertAlmostEqual(by_id.loc["P1", "pnl_units"], 1.0)
        self.assertAlmostEqual(by_id.loc["P2", "pnl_units"], -1.0)
        self.assertAlmostEqual(by_id.loc["P3", "pnl_units"], 0.0)

    def test_summary_roi_excludes_void_from_stake(self):
        out = pt.build_paper_test(self._predictions(), self._settlements())
        summary = pt.summarize_paper_test(out)
        self.assertEqual(summary["label"], cfg.PAPER_TEST_LABEL)
        self.assertEqual(summary["total_staked_units"], 2.0)
        self.assertAlmostEqual(summary["total_pnl_units"], 0.0)
        self.assertAlmostEqual(summary["roi"], 0.0)

    def test_never_uses_kelly_or_variable_stake(self):
        out = pt.build_paper_test(self._predictions(), self._settlements())
        self.assertTrue((out["stake_units"] == cfg.PAPER_TEST_FLAT_STAKE_UNITS).all())
        self.assertNotIn("kelly_fraction", out.columns)
        self.assertNotIn("recommended_stake_brl", out.columns)


class TestMetrics(unittest.TestCase):
    def test_brier_score_known_example(self):
        df = pd.DataFrame({"operational_probability": [0.8, 0.6, 0.3], "outcome": [1, 0, 0]})
        expected = ((0.8 - 1) ** 2 + (0.6 - 0) ** 2 + (0.3 - 0) ** 2) / 3
        self.assertAlmostEqual(metrics.brier_score(df), expected)

    def test_log_loss_known_example(self):
        df = pd.DataFrame({"operational_probability": [0.8, 0.2], "outcome": [1, 0]})
        expected = -(math.log(0.8) + math.log(0.8)) / 2
        self.assertAlmostEqual(metrics.log_loss(df), expected)

    def test_only_win_loss_settlements_enter_metrics(self):
        predictions = pd.DataFrame([
            {"prediction_id": "P1", "operational_probability": 0.7, "market": "aces_player", "tour": "ATP", "surface_ctx": "Hard"},
            {"prediction_id": "P2", "operational_probability": 0.7, "market": "aces_player", "tour": "ATP", "surface_ctx": "Hard"},
        ])
        settlements = pd.DataFrame([
            {"prediction_id": "P1", "settlement": cfg.SETTLEMENT_WIN},
            {"prediction_id": "P2", "settlement": cfg.SETTLEMENT_VOID},
        ])
        df = metrics.with_outcome(predictions, settlements)
        self.assertEqual(len(df), 1)

    def test_sample_size_checkpoints_are_descriptive_only(self):
        checkpoints = metrics.sample_size_checkpoints(30)
        reached = {c["checkpoint"]: c["reached"] for c in checkpoints}
        self.assertTrue(reached[25])
        self.assertFalse(reached[50])


class TestThresholdAndClassificationComparison(unittest.TestCase):
    def test_threshold_comparison_never_declares_a_winner(self):
        predictions = pd.DataFrame([
            {"prediction_id": "P1", "operational_probability": 0.7, "status": "ATINGE_EDGE_2", "outcome": 1},
            {"prediction_id": "P2", "operational_probability": 0.6, "status": "ATINGE_EDGE_10", "outcome": 0},
        ])
        out = metrics.threshold_comparison(predictions, pd.DataFrame())
        self.assertEqual(len(out), len(cfg.EDGE_THRESHOLD_LABELS_CUMULATIVE))
        self.assertNotIn("winner", out.columns)
        self.assertNotIn("best_threshold", out.columns)

    def test_classification_comparison_reports_all_groups_separately(self):
        predictions = pd.DataFrame([
            {"prediction_id": "P1", "classification": "CANDIDATO"},
            {"prediction_id": "P2", "classification": "DESCARTAR"},
        ])
        settlements = pd.DataFrame([
            {"prediction_id": "P1", "settlement": cfg.SETTLEMENT_WIN},
            {"prediction_id": "P2", "settlement": cfg.SETTLEMENT_LOSS},
        ])
        out = metrics.classification_comparison(predictions, settlements, pd.DataFrame())
        self.assertEqual(set(out["classification"]), {"CANDIDATO", "DESCARTAR"})


class TestNoTemporalLeakage(unittest.TestCase):
    def setUp(self):
        _use_temp_dirs(self)

    def test_prediction_probability_unaffected_by_later_result(self):
        preds.register_predictions(pd.DataFrame([_base_opportunity()]))
        before = pd.read_parquet(cfg.FORWARD_PREDICTIONS_PATH).iloc[0]["operational_probability"]

        result_entry = {"tour": "ATP", "match_id": "FUTURE:ATP:0", "match_status": "completed",
                         "player_a": "Sebastian Baez", "player_b": "Jenson Brooksby",
                         "aces_player_a": 8, "aces_player_b": 4}
        res.record_result(result_entry)
        build.settle_day()

        after = pd.read_parquet(cfg.FORWARD_PREDICTIONS_PATH).iloc[0]["operational_probability"]
        self.assertEqual(before, after)

    def test_historical_data_cutoff_never_after_registration_time(self):
        stamp = versioning.current_version_stamp("ATP")
        cutoff = pd.Timestamp(stamp["historical_data_cutoff"])
        now = pd.Timestamp.now("UTC").tz_localize(None)
        self.assertLessEqual(cutoff, now)


class TestIds(unittest.TestCase):
    def test_prediction_id_stable_and_deterministic(self):
        a = ids.make_prediction_id("Betano", "ATP", "M1", "aces_player", "Player X", "over", 5.5)
        b = ids.make_prediction_id("Betano", "ATP", "M1", "aces_player", "Player X", "over", 5.5)
        self.assertEqual(a, b)

    def test_prediction_id_changes_with_any_key_field(self):
        a = ids.make_prediction_id("Betano", "ATP", "M1", "aces_player", "Player X", "over", 5.5)
        b = ids.make_prediction_id("Betano", "ATP", "M1", "aces_player", "Player X", "under", 5.5)
        self.assertNotEqual(a, b)


class TestBuildEndToEnd(unittest.TestCase):
    def setUp(self):
        _use_temp_dirs(self)

    def test_register_settle_report_pipeline(self):
        preds.register_predictions(pd.DataFrame([_base_opportunity()]))
        result_entry = {"tour": "ATP", "match_id": "FUTURE:ATP:0", "match_status": "completed",
                         "player_a": "Sebastian Baez", "player_b": "Jenson Brooksby",
                         "aces_player_a": 8, "aces_player_b": 4}
        res.record_result(result_entry)
        settle_summary = build.settle_day()
        self.assertEqual(settle_summary["paper_test_summary"]["label"], cfg.PAPER_TEST_LABEL)

        report = build.daily_report(date_label=pd.Timestamp.now("UTC").date().isoformat())
        self.assertIn("HOJE / TODAY", report)
        dashboard = build.cumulative_dashboard()
        self.assertIn("Numero de previsoes historicas / Number of historical predictions: 1", dashboard)


if __name__ == "__main__":
    unittest.main()
