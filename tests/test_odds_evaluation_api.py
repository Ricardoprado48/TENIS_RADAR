"""Testes de integracao HTTP do LOTE G (docs/018_PWA_ARQUITETURA.md secao
9 + instrucoes do LOTE G): POST /api/screenshots/{upload_id}/evaluate.

Mesmo padrao de `tests/test_screenshot_extraction_api.py` (LOTE F):
diretorios reais substituidos por temporarios, nenhum arquivo do projeto e
tocado. `data/outputs/phase8/precos_por_linha.parquet` (entrada, real,
Fase 8) continua sendo lido de verdade -- so as SAIDAS das Fases 9/10 sao
redirecionadas, mesmo padrao aceito por
`tests/test_decision.py::TestBuildEndToEndWithRealData` (skipTest quando o
arquivo nao existir nesta maquina).
"""

from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from api.main import app
from src.decision import config as decision_cfg
from src.forward import config as forward_cfg
from src.odds import config as odds_cfg
from src.screenshot_parser.models import MatchContext

DEFAULT_MATCH_KEY = "atp-chengdu-open-r32-sebastian-baez-jenson-brooksby-2026-09-23"
_CONTEXT = MatchContext(
    match_key=DEFAULT_MATCH_KEY, tour="ATP", tournament="Chengdu Open",
    player_a="Sebastian Baez", player_b="Jenson Brooksby",
)


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (20, 20), color=(10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


PNG_BYTES = _png_bytes()


class _EvaluateApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        if not odds_cfg.PHASE8_PRICES_PATH.exists():
            self.skipTest("data/outputs/phase8/precos_por_linha.parquet nao existe nesta maquina")

        self.client = TestClient(app)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)

        self._orig = {}
        for mod, attrs in [
            (odds_cfg, ["PHASE9_DIR", "ODDS_OBSERVED_PATH", "COMPARISON_PATH", "DAILY_CHECK_PATH", "SNAPSHOTS_HISTORY_PATH"]),
            (decision_cfg, ["PHASE9_COMPARISON_PATH", "PHASE10_DIR", "OPPORTUNITIES_PATH", "OPERATIONAL_RULES_PATH", "CLASSIFICATION_SUMMARY_PATH", "REJECTED_PATH", "PHASE10_SUMMARY_PATH"]),
            # LOTE H: `odds_evaluation_service` agora consulta
            # `src.forward.build.is_registered` -- so leitura, mas isolada
            # do ledger real mesmo assim (mesma disciplina desta suite).
            (forward_cfg, ["FORWARD_PREDICTIONS_PATH"]),
        ]:
            for attr in attrs:
                self._orig[(mod, attr)] = getattr(mod, attr)
        self.addCleanup(self._restore)

        odds_cfg.PHASE9_DIR = tmp / "phase9"
        odds_cfg.ODDS_OBSERVED_PATH = odds_cfg.PHASE9_DIR / "odds_observed.parquet"
        odds_cfg.COMPARISON_PATH = odds_cfg.PHASE9_DIR / "comparison_with_model.parquet"
        odds_cfg.DAILY_CHECK_PATH = odds_cfg.PHASE9_DIR / "daily_odds_check.csv"
        odds_cfg.SNAPSHOTS_HISTORY_PATH = odds_cfg.PHASE9_DIR / "snapshots_history.parquet"

        decision_cfg.PHASE9_COMPARISON_PATH = odds_cfg.COMPARISON_PATH
        decision_cfg.PHASE10_DIR = tmp / "phase10"
        decision_cfg.OPPORTUNITIES_PATH = decision_cfg.PHASE10_DIR / "opportunities_evaluated.parquet"
        decision_cfg.OPERATIONAL_RULES_PATH = decision_cfg.PHASE10_DIR / "operational_rules.json"
        decision_cfg.CLASSIFICATION_SUMMARY_PATH = decision_cfg.PHASE10_DIR / "classification_summary.csv"
        decision_cfg.REJECTED_PATH = decision_cfg.PHASE10_DIR / "rejected_opportunities.csv"
        decision_cfg.PHASE10_SUMMARY_PATH = decision_cfg.PHASE10_DIR / "phase10_summary.json"

        forward_cfg.FORWARD_PREDICTIONS_PATH = tmp / "phase11" / "forward_predictions.parquet"

        self._patchers = [
            patch("src.screenshot_parser.config.SCREENSHOTS_RAW_DIR", tmp / "screenshots"),
            patch("src.screenshot_parser.config.EXTRACTED_RAW_DIR", tmp / "extracted"),
            patch("src.screenshot_parser.config.CONFIRMED_DIR", tmp / "confirmed"),
            patch("src.screenshot_parser.extractor._build_match_context", return_value=_CONTEXT),
        ]
        for p in self._patchers:
            p.start()
            self.addCleanup(p.stop)

    def _restore(self) -> None:
        for (mod, attr), value in self._orig.items():
            setattr(mod, attr, value)

    def _upload(self) -> str:
        resp = self.client.post(
            "/api/screenshots",
            data={"match_key": DEFAULT_MATCH_KEY, "tab_type": "ACES"},
            files={"image": ("print.png", PNG_BYTES, "image/png")},
        )
        self.assertEqual(resp.status_code, 201)
        return resp.json()["upload_id"]

    def _confirm(self, upload_id: str, markets: list[dict]):
        return self.client.post(f"/api/screenshots/{upload_id}/confirm", json={"markets": markets})

    def _evaluate(self, upload_id: str):
        return self.client.post(f"/api/screenshots/{upload_id}/evaluate")


class TestEvaluateEndpoint(_EvaluateApiTestCase):
    def test_evaluate_confirmed_aces_player(self) -> None:
        upload_id = self._upload()
        confirm_resp = self._confirm(upload_id, [
            {"market": "aces_player", "player": "Sebastian Baez", "bookmaker_display": "6+", "decimal_odds": 2.92},
        ])
        self.assertEqual(confirm_resp.status_code, 200)

        resp = self._evaluate(upload_id)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["upload_id"], upload_id)
        self.assertEqual(body["match_key"], DEFAULT_MATCH_KEY)
        self.assertIn("staleness_warning", body)
        self.assertIsNotNone(body["staleness_warning"])

        result = body["results"][0]
        self.assertEqual(result["market"], "aces_player")
        self.assertEqual(result["bookmaker_odds"], 2.92)
        self.assertIn(result["decision_state"], decision_cfg.STATES_ORDER)
        self.assertIn(result["evaluation_label"], ("PASSOU_DO_LIMITE", "OBSERVAR", "NAO_PASSOU"))
        self.assertIsNotNone(result["technical"])

        # LOTE H: chave/estado de registro no Forward Test, sem duplicar
        # nenhuma probabilidade/odd/classificacao.
        self.assertIsNotNone(result["forward_key"])
        self.assertEqual(result["forward_key"]["market"], "aces_player")
        self.assertIsNotNone(result["prediction_id"])
        self.assertFalse(result["already_registered_forward_test"])

    def test_evaluate_unsupported_market_has_no_forward_key(self) -> None:
        upload_id = self._upload()
        self._confirm(upload_id, [
            {"market": "total_games", "player": None, "bookmaker_display": "Mais de 22.5", "decimal_odds": 1.85},
        ])
        result = self._evaluate(upload_id).json()["results"][0]
        self.assertIsNone(result["forward_key"])
        self.assertIsNone(result["prediction_id"])
        self.assertFalse(result["already_registered_forward_test"])

    def test_evaluate_total_games_is_not_modeled(self) -> None:
        upload_id = self._upload()
        self._confirm(upload_id, [
            {"market": "total_games", "player": None, "bookmaker_display": "Mais de 22.5", "decimal_odds": 1.85},
        ])

        resp = self._evaluate(upload_id)
        self.assertEqual(resp.status_code, 200)
        result = resp.json()["results"][0]
        self.assertEqual(result["evaluation_label"], "SEM_AVALIACAO_DISPONIVEL")
        self.assertIsNone(result["decision_state"])

    def test_evaluate_unknown_upload_is_404(self) -> None:
        resp = self._evaluate("does-not-exist")
        self.assertEqual(resp.status_code, 404)

    def test_evaluate_unconfirmed_upload_is_404(self) -> None:
        upload_id = self._upload()
        resp = self._evaluate(upload_id)
        self.assertEqual(resp.status_code, 404)

    def test_evaluate_missing_match_context_is_422(self) -> None:
        upload_id = self._upload()
        self._confirm(upload_id, [
            {"market": "aces_player", "player": "Sebastian Baez", "bookmaker_display": "6+", "decimal_odds": 2.92},
        ])
        with patch("src.screenshot_parser.extractor._build_match_context", return_value=None):
            resp = self._evaluate(upload_id)
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
