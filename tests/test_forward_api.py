"""Testes de integracao HTTP do LOTE H (docs/018 secao 22): GET
/api/forward/summary, GET /api/forward/predictions,
GET /api/forward/predictions/{prediction_id}, POST /api/forward/register.

So LEITURA/organizacao sobre o que a Fase 11 ja calculou (mesma disciplina
de `tests/test_forward.py`: diretorios reais substituidos por temporarios,
`_use_temp_dirs`/`_base_opportunity` reaproveitados, nenhuma formula
reimplementada aqui)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from api.main import app
from src.forward import build as fwd_build
from src.forward import config as cfg
from src.forward import predictions as preds
from src.forward import results as res

from tests.test_forward import _base_opportunity, _use_temp_dirs


class _ForwardApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        _use_temp_dirs(self)


class TestEmptyState(_ForwardApiTestCase):
    def test_summary_empty(self) -> None:
        resp = self.client.get("/api/forward/summary")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["counts"], {
            "n_predictions_registered": 0, "n_pending_settlement": 0, "n_resolved": 0,
            "n_candidates": 0, "n_observar": 0, "n_descartados": 0,
        })
        self.assertEqual(body["results"], {"wins": 0, "losses": 0, "void": 0, "pending": 0})
        self.assertEqual(body["paper_test"]["n_entries_simulated"], 0)
        # metricas ausentes -- nunca inventadas.
        self.assertIsNone(body["technical"]["brier_score_overall"])
        self.assertIsNone(body["technical"]["log_loss_overall"])
        self.assertEqual(body["technical"]["calibration"], [])
        self.assertEqual(body["technical"]["by_market"], [])

    def test_predictions_list_empty(self) -> None:
        resp = self.client.get("/api/forward/predictions")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"items": [], "total": 0, "limit": 50, "offset": 0})

    def test_prediction_detail_not_found(self) -> None:
        resp = self.client.get("/api/forward/predictions/PRED_0000000000000000")
        self.assertEqual(resp.status_code, 404)


class TestRegisteredButUnsettled(_ForwardApiTestCase):
    """Previsoes registradas, nenhuma settled ainda -- metricas (Brier/Log
    Loss/CLV) precisam continuar ausentes (None), nunca inventadas so
    porque ha previsoes."""

    def setUp(self) -> None:
        super().setUp()
        preds.register_predictions(pd.DataFrame([_base_opportunity()]))

    def test_summary_shows_pending_without_metrics(self) -> None:
        body = self.client.get("/api/forward/summary").json()
        self.assertEqual(body["counts"]["n_predictions_registered"], 1)
        self.assertEqual(body["counts"]["n_pending_settlement"], 1)
        self.assertEqual(body["counts"]["n_resolved"], 0)
        self.assertIsNone(body["technical"]["brier_score_overall"])

    def test_prediction_detail_is_unresolved_without_clv_or_odds_history(self) -> None:
        pid = self.client.get("/api/forward/predictions").json()["items"][0]["prediction_id"]
        body = self.client.get(f"/api/forward/predictions/{pid}").json()
        self.assertEqual(body["settlement"], cfg.SETTLEMENT_UNRESOLVED)
        self.assertIsNone(body["clv"])
        self.assertIsNone(body["odds_history"])
        self.assertIsNone(body["paper_result_units"])
        self.assertIn("model_edge", body["technical"])


class TestSummaryAndListingWithSettledData(_ForwardApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        preds.register_predictions(pd.DataFrame([
            _base_opportunity(classification="CANDIDATO"),
            _base_opportunity(
                market="total_aces_match", player=None, opponent=None, side="over", line=13.5,
                classification="OBSERVAR", decimal_odds=2.0, operational_probability=0.55, fair_odds=1.818,
            ),
            _base_opportunity(classification="DESCARTAR", line=20.5, decimal_odds=1.2),
        ]))
        res.record_result({
            "tour": "ATP", "match_id": "FUTURE:ATP:0", "match_status": "completed",
            "player_a": "Sebastian Baez", "player_b": "Jenson Brooksby",
            "aces_player_a": 8, "aces_player_b": 4,
        })
        fwd_build.settle_day()

    def test_summary_classification_counts(self) -> None:
        body = self.client.get("/api/forward/summary").json()
        self.assertEqual(body["counts"]["n_predictions_registered"], 3)
        self.assertEqual(body["counts"]["n_candidates"], 1)
        self.assertEqual(body["counts"]["n_observar"], 1)
        self.assertEqual(body["counts"]["n_descartados"], 1)
        self.assertEqual(body["counts"]["n_resolved"], 3)

    def test_summary_result_counts_match_settlement(self) -> None:
        body = self.client.get("/api/forward/summary").json()
        # aces_player linha 5.5 over, real=8 -> WIN; total_aces_match linha
        # 13.5 over, real=12 -> LOSS; aces_player linha 20.5 over, real=8 -> LOSS.
        self.assertEqual(body["results"], {"wins": 1, "losses": 2, "void": 0, "pending": 0})

    def test_predictions_list_total_and_filters(self) -> None:
        self.assertEqual(self.client.get("/api/forward/predictions").json()["total"], 3)

        candidatos = self.client.get("/api/forward/predictions", params={"classification_group": "candidato"}).json()
        self.assertEqual(candidatos["total"], 1)

        resolvidas = self.client.get("/api/forward/predictions", params={"settlement_group": "resolvidas"}).json()
        self.assertEqual(resolvidas["total"], 3)

        wta = self.client.get("/api/forward/predictions", params={"tour": "WTA"}).json()
        self.assertEqual(wta["total"], 0)

    def test_predictions_list_pagination(self) -> None:
        page1 = self.client.get("/api/forward/predictions", params={"limit": 2, "offset": 0}).json()
        page2 = self.client.get("/api/forward/predictions", params={"limit": 2, "offset": 2}).json()
        self.assertEqual(len(page1["items"]), 2)
        self.assertEqual(len(page2["items"]), 1)
        self.assertEqual(page1["total"], 3)

    def test_prediction_detail_has_settlement_and_technical_metrics(self) -> None:
        items = self.client.get("/api/forward/predictions").json()["items"]
        win_item = next(i for i in items if i["classification"] == "CANDIDATO")
        body = self.client.get(f"/api/forward/predictions/{win_item['prediction_id']}").json()
        self.assertEqual(body["settlement"], "WIN")
        self.assertIsNotNone(body["settled_at"])
        self.assertIn("minimum_odds", body)

    def test_summary_technical_metrics_present_when_settled(self) -> None:
        body = self.client.get("/api/forward/summary").json()
        self.assertIsNotNone(body["technical"]["brier_score_overall"])
        self.assertIsNotNone(body["technical"]["log_loss_overall"])
        markets = {m["market"] for m in body["technical"]["by_market"]}
        self.assertIn("aces_player", markets)


class TestRegisterEndpoint(_ForwardApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._orig_phase9 = cfg.PHASE9_OBSERVATIONS_PATH
        self._orig_phase10 = cfg.PHASE10_OPPORTUNITIES_PATH
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmp_dir = Path(tmp.name)
        cfg.PHASE10_OPPORTUNITIES_PATH = tmp_dir / "opportunities_evaluated.parquet"
        cfg.PHASE9_OBSERVATIONS_PATH = tmp_dir / "odds_observed.parquet"
        self.addCleanup(lambda: setattr(cfg, "PHASE10_OPPORTUNITIES_PATH", self._orig_phase10))
        self.addCleanup(lambda: setattr(cfg, "PHASE9_OBSERVATIONS_PATH", self._orig_phase9))

        self.opp = _base_opportunity()
        cfg.PHASE10_OPPORTUNITIES_PATH.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([self.opp]).to_parquet(cfg.PHASE10_OPPORTUNITIES_PATH, index=False)
        pd.DataFrame([{
            "bookmaker": self.opp["bookmaker"], "match_id": self.opp["match_id"], "tour": self.opp["tour"],
            "market": self.opp["market"], "player": self.opp["player"], "side": self.opp["side"],
            "line": self.opp["line"], "collected_at": self.opp["collected_at"],
            "tournament": self.opp["tournament"], "opponent": self.opp["opponent"],
        }]).to_parquet(cfg.PHASE9_OBSERVATIONS_PATH, index=False)

    def _payload(self, **overrides) -> dict:
        opp = self.opp
        payload = {
            "bookmaker": opp["bookmaker"], "tour": opp["tour"], "match_id": opp["match_id"],
            "market": opp["market"], "player": opp["player"], "side": opp["side"], "line": opp["line"],
            "decimal_odds": opp["decimal_odds"], "collected_at": opp["collected_at"],
        }
        payload.update(overrides)
        return payload

    def test_register_valid_opportunity(self) -> None:
        resp = self.client.post("/api/forward/register", json=self._payload())
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "registered")
        self.assertIsNotNone(body["prediction_id"])
        self.assertEqual(len(preds.load_predictions()), 1)

    def test_register_duplicate_is_reported_not_duplicated(self) -> None:
        first = self.client.post("/api/forward/register", json=self._payload()).json()
        second = self.client.post("/api/forward/register", json=self._payload()).json()
        self.assertEqual(second["status"], "already_registered")
        self.assertEqual(first["prediction_id"], second["prediction_id"])
        self.assertEqual(len(preds.load_predictions()), 1)

    def test_register_unknown_opportunity(self) -> None:
        resp = self.client.post("/api/forward/register", json=self._payload(line=999.5))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "not_found")


if __name__ == "__main__":
    unittest.main()
