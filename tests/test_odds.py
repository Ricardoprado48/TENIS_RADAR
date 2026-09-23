"""Testes da Fase 9 (item 14): conversao odd -> probabilidade, Over/Under,
overround, no-vig, comparacao com odd minima, snapshots multiplos,
timestamps, duplicacao, mercados inexistentes, linha da casa diferente da
linha do modelo, aplicacao das restricoes da Fase 7, warning de dados
defasados."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.odds import build
from src.odds import config as cfg
from src.odds import matching
from src.odds import pricing_compare as pc
from src.odds import storage


def _fake_price_row(**overrides) -> dict:
    row = {
        "tour": "ATP",
        "market": "aces_player",
        "player_id": "ATP-999001",
        "player_name": "sebastian baez",
        "opponent_name": "jenson brooksby",
        "line": 7.5,
        "side": "over",
        "match_id": "FUTURE:ATP:0",
        "tournament": "Chengdu Open",
        "surface_ctx": "Hard",
        "match_date": pd.Timestamp("2026-09-23"),
        "round": "R32",
        "resolution_method_player": "exact",
        "resolution_method_opponent": "exact",
        "operational_probability": 0.63,
        "fair_odds": 1.5873015873015872,
        "sample_bucket_career": "large_50_plus",
        "prior_matches_career": 106,
        "method_selected": "platt",
        "restricted": False,
        "restricted_motivo": None,
        "extreme_probability": False,
        "insufficient_history": False,
        "cold_start": False,
        "is_candidate": True,
    }
    row.update(overrides)
    return row


def _fake_prices_frame() -> pd.DataFrame:
    over = _fake_price_row(side="over", operational_probability=0.63)
    under = _fake_price_row(side="under", operational_probability=0.37)
    return pd.DataFrame([over, under])


class _IsolatedOutputMixin:
    """Redireciona cfg.PHASE9_DIR/* para um diretorio temporario, para nao
    tocar em data/outputs/phase9 real durante os testes (mesmo padrao de
    isolamento usado em tests/test_incremental.py::TestRadarAfterUpdate)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self._tmp.name)
        self._orig = {
            "PHASE9_DIR": cfg.PHASE9_DIR,
            "ODDS_OBSERVED_PATH": cfg.ODDS_OBSERVED_PATH,
            "COMPARISON_PATH": cfg.COMPARISON_PATH,
            "DAILY_CHECK_PATH": cfg.DAILY_CHECK_PATH,
            "SNAPSHOTS_HISTORY_PATH": cfg.SNAPSHOTS_HISTORY_PATH,
        }
        cfg.PHASE9_DIR = tmp_dir
        cfg.ODDS_OBSERVED_PATH = tmp_dir / "odds_observed.parquet"
        cfg.COMPARISON_PATH = tmp_dir / "comparison_with_model.parquet"
        cfg.DAILY_CHECK_PATH = tmp_dir / "daily_odds_check.csv"
        cfg.SNAPSHOTS_HISTORY_PATH = tmp_dir / "snapshots_history.parquet"

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(cfg, k, v)
        self._tmp.cleanup()


class TestOddsToProbability(unittest.TestCase):
    def test_implied_probability_is_inverse_of_odds(self):
        out = pc.compare_one(0.63, 1.80)
        self.assertAlmostEqual(out["implied_probability"], 1.0 / 1.80, places=8)

    def test_model_edge_is_model_minus_implied(self):
        out = pc.compare_one(0.63, 1.80)
        self.assertAlmostEqual(out["model_edge"], 0.63 - (1.0 / 1.80), places=8)


class TestOverUnder(_IsolatedOutputMixin, unittest.TestCase):
    def test_both_sides_recorded_as_two_linked_rows(self):
        prices = _fake_prices_frame()
        entry = {
            "bookmaker": "Betano", "tour": "ATP", "market": "aces_player",
            "player": "Sebastian Baez", "line": 7.5,
            "over_odds": 1.90, "under_odds": 1.95,
            "collected_at": "2026-09-22T14:00:00+00:00",
        }
        result = build.record_entry(entry, prices)
        self.assertEqual(len(result["observations"]), 2)
        self.assertEqual(set(result["observations"]["side"]), {"over", "under"})
        self.assertEqual(set(result["comparisons"]["match_id"]), {"FUTURE:ATP:0"})


class TestOverround(unittest.TestCase):
    def test_overround_positive_for_realistic_book_prices(self):
        out = pc.overround_and_novig(1.90, 1.90)
        self.assertAlmostEqual(out["implied_probability_over"], 1 / 1.90, places=8)
        self.assertGreater(out["overround"], 0.0)

    def test_overround_nan_when_only_one_side_given(self):
        out = pc.overround_and_novig(1.90, None)
        self.assertNotEqual(out["overround"], out["overround"])  # NaN


class TestNoVig(unittest.TestCase):
    def test_novig_probabilities_sum_to_one(self):
        out = pc.overround_and_novig(1.90, 1.95)
        total = out["novig_probability_over"] + out["novig_probability_under"]
        self.assertAlmostEqual(total, 1.0, places=8)

    def test_real_odds_never_replaced_by_novig(self):
        prices = _fake_prices_frame()
        entry = {
            "bookmaker": "Betano", "tour": "ATP", "market": "aces_player",
            "player": "Sebastian Baez", "line": 7.5,
            "over_odds": 1.90, "under_odds": 1.95,
            "collected_at": "2026-09-22T14:00:00+00:00",
        }
        result = build.record_entry(entry, prices)
        obs = result["observations"]
        self.assertAlmostEqual(float(obs[obs["side"] == "over"]["decimal_odds"].iloc[0]), 1.90)
        self.assertAlmostEqual(float(obs[obs["side"] == "under"]["decimal_odds"].iloc[0]), 1.95)


class TestMinimumOddsComparison(unittest.TestCase):
    def test_status_matches_instructions_example(self):
        # p=0.63 (docs/012 exemplo 3 / instrucao Fase 9 item 9): odd justa
        # 1.59, minima edge 5% = 1.72. Odd 1.80 >= 1.72 -> ATINGE_EDGE_5,
        # mas < odd minima edge 7.5% (1.80) -> no maximo ATINGE_EDGE_5.
        status = pc.classify_status(0.63, 1.80)
        self.assertEqual(status, cfg.EDGE_STATUS_LABELS["5pct"])

    def test_status_below_threshold_when_odds_too_low(self):
        status = pc.classify_status(0.63, 1.55)
        self.assertEqual(status, cfg.STATUS_BELOW_THRESHOLD)

    def test_status_increases_with_odds(self):
        statuses = [pc.classify_status(0.63, o) for o in (1.55, 1.65, 1.75, 1.85, 2.0, 2.2)]
        levels = [cfg.STATUS_BELOW_THRESHOLD] + list(cfg.EDGE_STATUS_LABELS.values())
        ranks = [levels.index(s) for s in statuses]
        self.assertEqual(ranks, sorted(ranks))


class TestMultipleSnapshots(_IsolatedOutputMixin, unittest.TestCase):
    def test_two_timestamps_same_line_both_preserved(self):
        prices = _fake_prices_frame()
        entry1 = {
            "bookmaker": "Betano", "tour": "ATP", "market": "aces_player",
            "player": "Sebastian Baez", "line": 7.5, "over_odds": 1.75,
            "collected_at": "2026-09-22T14:00:00+00:00",
        }
        entry2 = dict(entry1, over_odds=1.88, collected_at="2026-09-22T16:00:00+00:00")

        build.run_manual_entries([entry1])
        build.run_manual_entries([entry2])

        obs = pd.read_parquet(cfg.ODDS_OBSERVED_PATH)
        self.assertEqual(len(obs), 2)
        self.assertEqual(sorted(obs["decimal_odds"].tolist()), [1.75, 1.88])

        snap = storage.rebuild_snapshots_history()
        snap = snap.sort_values("collected_at")
        self.assertEqual(snap["snapshot_seq"].tolist(), [1, 2])
        self.assertTrue(pd.isna(snap["line_move_from_previous"].iloc[0]))
        self.assertAlmostEqual(snap["line_move_from_previous"].iloc[1], 1.88 - 1.75, places=8)


class TestTimestamps(_IsolatedOutputMixin, unittest.TestCase):
    def test_default_collected_at_is_filled_and_parseable(self):
        prices = _fake_prices_frame()
        entry = {
            "bookmaker": "Betano", "tour": "ATP", "market": "aces_player",
            "player": "Sebastian Baez", "line": 7.5, "over_odds": 1.75,
        }
        result = build.record_entry(entry, prices)
        collected_at = result["observations"]["collected_at"].iloc[0]
        self.assertIsNotNone(collected_at)
        pd.Timestamp(collected_at)  # nao deve lancar

    def test_explicit_collected_at_is_preserved_verbatim(self):
        prices = _fake_prices_frame()
        entry = {
            "bookmaker": "Betano", "tour": "ATP", "market": "aces_player",
            "player": "Sebastian Baez", "line": 7.5, "over_odds": 1.75,
            "collected_at": "2026-09-22T14:00:00+00:00",
        }
        result = build.record_entry(entry, prices)
        self.assertEqual(result["observations"]["collected_at"].iloc[0], "2026-09-22T14:00:00+00:00")


class TestDuplication(_IsolatedOutputMixin, unittest.TestCase):
    def test_exact_resubmission_not_double_counted(self):
        entry = {
            "bookmaker": "Betano", "tour": "ATP", "market": "aces_player",
            "player": "Sebastian Baez", "line": 7.5, "over_odds": 1.75,
            "collected_at": "2026-09-22T14:00:00+00:00",
        }
        r1 = build.run_manual_entries([entry])
        r2 = build.run_manual_entries([entry])
        self.assertEqual(r1["n_observation_rows_total_ledger"], 1)
        self.assertEqual(r2["n_observation_rows_total_ledger"], 1)


class TestNonexistentMarket(unittest.TestCase):
    def test_market_outside_scope_is_rejected(self):
        entry = {
            "bookmaker": "Betano", "tour": "ATP", "market": "total_games",
            "player": "Sebastian Baez", "line": 21.5, "over_odds": 1.90,
        }
        with self.assertRaises(ValueError):
            build.validate_entry(entry)

    def test_invalid_tour_is_rejected(self):
        entry = {
            "bookmaker": "Betano", "tour": "ITF", "market": "aces_player",
            "player": "Sebastian Baez", "line": 7.5, "over_odds": 1.90,
        }
        with self.assertRaises(ValueError):
            build.validate_entry(entry)

    def test_no_side_odds_given_is_rejected(self):
        entry = {
            "bookmaker": "Betano", "tour": "ATP", "market": "aces_player",
            "player": "Sebastian Baez", "line": 7.5,
        }
        with self.assertRaises(ValueError):
            build.validate_entry(entry)


class TestLineDifferentFromModel(unittest.TestCase):
    def test_line_not_in_model_grid_is_unmatched_but_recorded(self):
        prices = _fake_prices_frame()
        match = matching.match_against_radar("ATP", "aces_player", "Sebastian Baez", 99.5, "over", prices)
        self.assertFalse(match["matched"])
        self.assertIn("nao existe na grade do modelo", match["match_reason"])

        entry = {
            "bookmaker": "Betano", "tour": "ATP", "market": "aces_player",
            "player": "Sebastian Baez", "line": 99.5, "over_odds": 2.0,
        }
        result = build.record_entry(entry, prices)
        self.assertEqual(len(result["observations"]), 1)
        self.assertEqual(result["observations"]["match_id"].iloc[0], "UNMATCHED")
        self.assertFalse(result["comparisons"]["matched"].iloc[0])
        self.assertTrue(pd.isna(result["comparisons"]["operational_probability"].iloc[0]))

    def test_unknown_player_is_unmatched_but_recorded(self):
        prices = _fake_prices_frame()
        entry = {
            "bookmaker": "Betano", "tour": "ATP", "market": "aces_player",
            "player": "Jogador Inexistente Zzz", "line": 7.5, "over_odds": 2.0,
        }
        result = build.record_entry(entry, prices)
        self.assertFalse(result["comparisons"]["matched"].iloc[0])
        self.assertEqual(len(result["observations"]), 1)


class TestRestrictionApplied(unittest.TestCase):
    def test_restricted_flag_from_phase7_propagates_to_comparison(self):
        prices = pd.DataFrame([
            _fake_price_row(
                side="over", tour="ATP", market="aces_player", surface_ctx="Grass",
                restricted=True, restricted_motivo="ECE piora em Grass apos Platt",
            )
        ])
        entry = {
            "bookmaker": "Betano", "tour": "ATP", "market": "aces_player",
            "player": "Sebastian Baez", "line": 7.5, "over_odds": 1.80,
        }
        result = build.record_entry(entry, prices)
        cmp_row = result["comparisons"].iloc[0]
        self.assertTrue(cmp_row["matched"])
        self.assertTrue(cmp_row["restricted"])
        self.assertEqual(cmp_row["restricted_motivo"], "ECE piora em Grass apos Platt")


class TestStalenessWarning(unittest.TestCase):
    def test_staleness_warning_present_and_not_hidden(self):
        out = pc.staleness_warning("ATP")
        self.assertIn("historical_data_cutoff", out)
        self.assertIn("data_staleness_days", out)
        self.assertGreaterEqual(out["data_staleness_days"], 0)
        self.assertIn(out["historical_data_cutoff"], out["staleness_warning"])

    def test_staleness_carried_through_full_comparison(self):
        prices = _fake_prices_frame()
        entry = {
            "bookmaker": "Betano", "tour": "ATP", "market": "aces_player",
            "player": "Sebastian Baez", "line": 7.5, "over_odds": 1.80,
        }
        result = build.record_entry(entry, prices)
        cmp_row = result["comparisons"].iloc[0]
        self.assertIn("historical_data_cutoff", cmp_row)
        self.assertIn("data_staleness_days", cmp_row)


class TestManualEntryEndToEndWithRealRadar(_IsolatedOutputMixin, unittest.TestCase):
    def test_real_phase8_radar_produces_matched_comparison(self):
        prices = build.load_current_radar()
        real_row = prices[(prices["tour"] == "ATP") & (prices["market"] == "aces_player") & (prices["side"] == "over")].iloc[0]
        entry = {
            "bookmaker": "Betano", "tour": "ATP", "market": "aces_player",
            "player": real_row["player_name"], "line": float(real_row["line"]),
            "over_odds": 1.80,
        }
        result = build.run_manual_entries([entry])
        self.assertEqual(result["n_entries_rejected"], 0)
        self.assertEqual(result["n_observation_rows_recorded_this_run"], 1)
        self.assertTrue(cfg.COMPARISON_PATH.exists())


if __name__ == "__main__":
    unittest.main()
