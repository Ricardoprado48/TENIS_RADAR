"""Testes do orquestrador `scripts/daily_forward_workflow.py` (camada
operacional sobre a Fase 11). So testa a ORQUESTRACAO -- quais funcoes ja
existentes sao chamadas, em que ordem, e o que e impresso -- nunca a logica
de negocio em si (registro imutavel, settlement, CLV, paper test, metricas),
que ja e coberta por `tests/test_forward.py` e nao e reexercitada aqui."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "daily_forward_workflow.py"


def _load_workflow_module():
    spec = importlib.util.spec_from_file_location("daily_forward_workflow", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


workflow = _load_workflow_module()


def _run_capture(func, *args, **kwargs) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        func(*args, **kwargs)
    return buf.getvalue()


def _predictions_df() -> pd.DataFrame:
    return pd.DataFrame([{
        "prediction_id": "PRED1", "tour": "ATP", "market": "aces_player",
        "player": "Baez", "side": "over", "line": 5.5,
        "operational_probability": 0.65, "fair_odds": 1.54, "classification": "CANDIDATO",
    }])


class TestMorningMode(unittest.TestCase):
    def test_runs_radar_then_registers_and_never_touches_bookmaker(self):
        radar_summary = {
            "n_matches_raw": 10, "n_matches_resolved_usable": 8, "n_matches_unresolved": 2,
            "n_price_rows": 20, "n_radar_candidates": 3,
        }
        register_result = {"n_registered": 4, "n_skipped_duplicates": 1, "n_rejected_overwrite_attempts": 0}

        with mock.patch.object(workflow.radar_build, "run", return_value=radar_summary) as m_run, \
                mock.patch.object(workflow.fwd_build, "register_day", return_value=register_result) as m_reg:
            args = workflow.argparse.Namespace(raw_path=None)
            out = _run_capture(workflow._mode_morning, args)

        m_run.assert_called_once_with(None)
        m_reg.assert_called_once_with()
        self.assertIn("Novas previsoes registradas: 4", out)
        self.assertIn("Nenhuma casa de apostas foi consultada", out)

    def test_flags_rejected_overwrite_attempts(self):
        radar_summary = {
            "n_matches_raw": 1, "n_matches_resolved_usable": 1, "n_matches_unresolved": 0,
            "n_price_rows": 1, "n_radar_candidates": 0,
        }
        register_result = {"n_registered": 0, "n_skipped_duplicates": 0, "n_rejected_overwrite_attempts": 2}
        with mock.patch.object(workflow.radar_build, "run", return_value=radar_summary), \
                mock.patch.object(workflow.fwd_build, "register_day", return_value=register_result):
            out = _run_capture(workflow._mode_morning, workflow.argparse.Namespace(raw_path="x.csv"))
        self.assertIn("ALERTA", out)


class TestOddsMode(unittest.TestCase):
    def test_no_args_shows_guidance_for_open_predictions(self):
        with mock.patch.object(workflow.fwd_preds, "load_predictions", return_value=_predictions_df()), \
                mock.patch.object(workflow.fwd_settle, "latest_settlements", return_value=pd.DataFrame()), \
                mock.patch.object(workflow.fwd_snaps, "summarize_odds_movement", return_value=pd.DataFrame()):
            args = workflow.argparse.Namespace(
                prediction_id=None, bookmaker="Betano", decimal_odds=None,
                collected_at=None, input_json=None,
            )
            out = _run_capture(workflow._mode_odds, args)
        self.assertIn("PRED1", out)
        self.assertIn("em aberto", out)

    def test_settled_predictions_excluded_from_guidance(self):
        settlements = pd.DataFrame([{"prediction_id": "PRED1", "settlement": "WIN"}])
        with mock.patch.object(workflow.fwd_preds, "load_predictions", return_value=_predictions_df()), \
                mock.patch.object(workflow.fwd_settle, "latest_settlements", return_value=settlements), \
                mock.patch.object(workflow.fwd_snaps, "summarize_odds_movement", return_value=pd.DataFrame()):
            args = workflow.argparse.Namespace(
                prediction_id=None, bookmaker="Betano", decimal_odds=None,
                collected_at=None, input_json=None,
            )
            out = _run_capture(workflow._mode_odds, args)
        self.assertIn("0 previsao", out)
        self.assertNotIn("PRED1", out)

    def test_recording_snapshot_calls_forward_infrastructure_and_compares_with_model(self):
        snapshot_df = pd.DataFrame([{"snapshot_id": "s1"}, {"snapshot_id": "s2"}])
        with mock.patch.object(workflow.fwd_preds, "load_predictions", return_value=_predictions_df()), \
                mock.patch.object(workflow.fwd_build, "record_odds_for_prediction", return_value=snapshot_df) as m_rec:
            args = workflow.argparse.Namespace(
                prediction_id="PRED1", bookmaker="Betano", decimal_odds=1.8,
                collected_at="2026-09-22T17:00:00+00:00", input_json=None,
            )
            out = _run_capture(workflow._mode_odds, args)

        m_rec.assert_called_once_with("PRED1", "Betano", 1.8, "2026-09-22T17:00:00+00:00")
        self.assertIn("2 snapshot(s)", out)
        self.assertIn("prob. modelo", out)
        self.assertIn("edge (modelo - implicita)", out)

    def test_unknown_prediction_id_is_flagged_not_crashed(self):
        with mock.patch.object(workflow.fwd_preds, "load_predictions", return_value=pd.DataFrame()), \
                mock.patch.object(
                    workflow.fwd_build, "record_odds_for_prediction",
                    return_value=pd.DataFrame([{"snapshot_id": "s1"}]),
                ):
            args = workflow.argparse.Namespace(
                prediction_id="DOES_NOT_EXIST", bookmaker="Betano", decimal_odds=1.5,
                collected_at=None, input_json=None,
            )
            out = _run_capture(workflow._mode_odds, args)
        self.assertIn("ALERTA", out)

    def test_input_json_batch_records_every_entry(self):
        entries = [
            {"prediction_id": "PRED1", "bookmaker": "Betano", "decimal_odds": 1.7, "collected_at": "2026-09-22T10:00:00+00:00"},
            {"prediction_id": "PRED1", "bookmaker": "Betano", "decimal_odds": 1.8, "collected_at": "2026-09-22T14:00:00+00:00"},
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(entries, f)
            path = f.name

        with mock.patch.object(workflow.fwd_preds, "load_predictions", return_value=_predictions_df()), \
                mock.patch.object(
                    workflow.fwd_build, "record_odds_for_prediction",
                    return_value=pd.DataFrame([{"snapshot_id": "s1"}]),
                ) as m_rec:
            args = workflow.argparse.Namespace(
                prediction_id=None, bookmaker="Betano", decimal_odds=None,
                collected_at=None, input_json=path,
            )
            _run_capture(workflow._mode_odds, args)

        self.assertEqual(m_rec.call_count, 2)


class TestSettleMode(unittest.TestCase):
    def test_records_results_then_settles(self):
        entries = [{"tour": "ATP", "match_id": "FUTURE:ATP:0", "match_status": "completed"}]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(entries, f)
            path = f.name

        with mock.patch.object(workflow.fwd_build, "record_match_result", return_value={"status": "recorded"}) as m_rec, \
                mock.patch.object(workflow.fwd_build, "settle_day", return_value={"n_new_settlement_events": 1}) as m_settle:
            args = workflow.argparse.Namespace(input_json=path)
            out = _run_capture(workflow._mode_settle, args)

        m_rec.assert_called_once_with(entries[0])
        m_settle.assert_called_once_with()
        self.assertIn("n_new_settlement_events", out)

    def test_without_input_json_only_resettles(self):
        with mock.patch.object(workflow.fwd_build, "record_match_result") as m_rec, \
                mock.patch.object(workflow.fwd_build, "settle_day", return_value={"n_new_settlement_events": 0}):
            args = workflow.argparse.Namespace(input_json=None)
            _run_capture(workflow._mode_settle, args)
        m_rec.assert_not_called()


class TestReportMode(unittest.TestCase):
    def test_prints_daily_report_dashboard_and_sample_size(self):
        preds_df = pd.DataFrame([{"prediction_id": "PRED1"}, {"prediction_id": "PRED2"}])
        with mock.patch.object(workflow.fwd_preds, "load_predictions", return_value=preds_df), \
                mock.patch.object(workflow.fwd_build, "daily_report", return_value="RELATORIO DIARIO X"), \
                mock.patch.object(workflow.fwd_build, "cumulative_dashboard", return_value="DASHBOARD Y"):
            out = _run_capture(workflow._mode_report, workflow.argparse.Namespace())

        self.assertIn("RELATORIO DIARIO X", out)
        self.assertIn("DASHBOARD Y", out)
        self.assertIn("2 previsao(oes) registrada(s)", out)


class TestCliDispatch(unittest.TestCase):
    def test_main_dispatches_to_each_mode_handler(self):
        for argv_mode, handler_name in [
            ("morning", "_mode_morning"), ("odds", "_mode_odds"),
            ("settle", "_mode_settle"), ("report", "_mode_report"),
        ]:
            with mock.patch.object(workflow, handler_name, return_value=0) as m_handler, \
                    mock.patch.object(sys, "argv", ["daily_forward_workflow.py", argv_mode]):
                rc = workflow.main()
            self.assertEqual(rc, 0)
            m_handler.assert_called_once()

    def test_missing_mode_is_a_cli_error(self):
        with mock.patch.object(sys, "argv", ["daily_forward_workflow.py"]):
            with self.assertRaises(SystemExit):
                workflow.main()


if __name__ == "__main__":
    unittest.main()
