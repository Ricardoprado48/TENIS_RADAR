"""Testes de integracao HTTP do LOTE F (docs/018_PWA_ARQUITETURA.md secao
9 + instrucoes do LOTE F): POST /api/screenshots/{id}/extract,
GET /api/screenshots/{id}/extraction, POST /api/screenshots/{id}/confirm.

Mesmo padrao de `tests/test_screenshots_api.py` (LOTE E): diretorios reais
substituidos por temporarios via mock.patch, nenhum arquivo do projeto e
tocado. O provider de visao e sempre um `FakeVisionProvider`/
`FailingVisionProvider` (`src.screenshot_parser.providers`) -- nenhuma
chamada real de IA entra nesta suite (pedido explicito).
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from api.main import app
from src.screenshot_parser import extraction_storage
from src.screenshot_parser.models import MatchContext, RawReading
from src.screenshot_parser.providers import (
    FailingVisionProvider,
    FakeVisionProvider,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

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


class _ExtractionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

        self._patchers = [
            patch("src.screenshot_parser.config.SCREENSHOTS_RAW_DIR", self.tmp_path / "screenshots"),
            patch("src.screenshot_parser.config.EXTRACTED_RAW_DIR", self.tmp_path / "extracted"),
            patch("src.screenshot_parser.config.CONFIRMED_DIR", self.tmp_path / "confirmed"),
            # Contexto de partida sempre disponivel e controlado nesta suite
            # -- nao depende de agenda_*.csv real (LOTE C, fora de escopo aqui).
            patch("src.screenshot_parser.extractor._build_match_context", return_value=_CONTEXT),
        ]
        for p in self._patchers:
            p.start()
            self.addCleanup(p.stop)

    def _upload(self, tab_type: str = "ACES") -> str:
        resp = self.client.post(
            "/api/screenshots",
            data={"match_key": DEFAULT_MATCH_KEY, "tab_type": tab_type},
            files={"image": ("print.png", PNG_BYTES, "image/png")},
        )
        self.assertEqual(resp.status_code, 201)
        return resp.json()["upload_id"]

    def _extract_with(self, upload_id: str, readings: list[RawReading]):
        provider = FakeVisionProvider(readings, raw_response="{}")
        with patch("src.screenshot_parser.providers.get_provider", return_value=provider):
            return self.client.post(f"/api/screenshots/{upload_id}/extract")


class TestExtractAces(_ExtractionTestCase):
    def test_valid_aces_player_block(self) -> None:
        upload_id = self._upload("ACES")
        resp = self._extract_with(upload_id, [
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="3+", decimal_odds=1.21),
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="4+", decimal_odds=1.52),
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="5+", decimal_odds=2.05),
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="6+", decimal_odds=2.92),
        ])
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "AUTO_VALIDATED")
        self.assertEqual(len(body["markets"]), 4)
        self.assertEqual(body["markets"][-1]["model_line"], 5.5)
        self.assertEqual(body["markets"][-1]["side"], "Over")

    def test_valid_total_aces_match(self) -> None:
        upload_id = self._upload("ACES")
        resp = self._extract_with(upload_id, [
            RawReading(market="total_aces_match", player=None, bookmaker_display="12+", decimal_odds=2.40),
        ])
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "AUTO_VALIDATED")
        self.assertIsNone(body["markets"][0]["player"])
        self.assertEqual(body["markets"][0]["model_line"], 11.5)

    def test_invalid_player_needs_confirmation(self) -> None:
        upload_id = self._upload("ACES")
        resp = self._extract_with(upload_id, [
            RawReading(market="aces_player", player="Novak Djokovic", bookmaker_display="6+", decimal_odds=2.0),
        ])
        body = resp.json()
        self.assertEqual(body["status"], "NEEDS_CONFIRMATION")
        self.assertIn("JOGADOR_NAO_RECONHECIDO", body["markets"][0]["warnings"])

    def test_odd_at_or_below_one_needs_confirmation(self) -> None:
        upload_id = self._upload("ACES")
        resp = self._extract_with(upload_id, [
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="6+", decimal_odds=1.0),
        ])
        body = resp.json()
        self.assertEqual(body["status"], "NEEDS_CONFIRMATION")
        self.assertIn("ODD_INVALIDA", body["markets"][0]["warnings"])

    def test_duplicate_reading_needs_confirmation(self) -> None:
        upload_id = self._upload("ACES")
        resp = self._extract_with(upload_id, [
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="6+", decimal_odds=2.0),
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="6+", decimal_odds=2.0),
        ])
        body = resp.json()
        self.assertEqual(body["status"], "NEEDS_CONFIRMATION")
        self.assertTrue(all("LEITURA_DUPLICADA" in m["warnings"] for m in body["markets"]))

    def test_non_monotonic_odds_warning(self) -> None:
        upload_id = self._upload("ACES")
        resp = self._extract_with(upload_id, [
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="3+", decimal_odds=1.21),
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="4+", decimal_odds=1.52),
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="5+", decimal_odds=7.05),
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="6+", decimal_odds=2.92),
        ])
        body = resp.json()
        self.assertEqual(body["status"], "NEEDS_CONFIRMATION")
        self.assertIn("ODDS_NON_MONOTONIC", body["markets"][2]["warnings"])


class TestExtractGames(_ExtractionTestCase):
    def test_valid_over_under_pair(self) -> None:
        upload_id = self._upload("GAMES_TOTALS")
        resp = self._extract_with(upload_id, [
            RawReading(market="total_games", player=None, bookmaker_display="Mais de 22.5", decimal_odds=1.85),
            RawReading(market="total_games", player=None, bookmaker_display="Menos de 22.5", decimal_odds=1.85),
        ])
        body = resp.json()
        self.assertEqual(body["status"], "AUTO_VALIDATED")
        sides = {m["side"] for m in body["markets"]}
        self.assertEqual(sides, {"Over", "Under"})

    def test_unpaired_line_needs_confirmation(self) -> None:
        upload_id = self._upload("GAMES_TOTALS")
        resp = self._extract_with(upload_id, [
            RawReading(market="total_games", player=None, bookmaker_display="Mais de 22.5", decimal_odds=1.85),
        ])
        body = resp.json()
        self.assertEqual(body["status"], "NEEDS_CONFIRMATION")
        self.assertIn("LINHA_SEM_PAR_OVER_UNDER", body["markets"][0]["warnings"])


class TestExtractEmptyAndErrors(_ExtractionTestCase):
    def test_no_markets_found(self) -> None:
        upload_id = self._upload("ACES")
        resp = self._extract_with(upload_id, [])
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "NEEDS_CONFIRMATION")
        self.assertEqual(body["markets"], [])
        self.assertIn("NENHUM_MERCADO_ENCONTRADO", body["extraction_warnings"])

    def test_provider_unavailable_maps_to_503(self) -> None:
        upload_id = self._upload("ACES")
        failing = FailingVisionProvider(ProviderUnavailableError("sem api key"))
        with patch("src.screenshot_parser.providers.get_provider", return_value=failing):
            resp = self.client.post(f"/api/screenshots/{upload_id}/extract")
        self.assertEqual(resp.status_code, 503)

    def test_provider_timeout_maps_to_504(self) -> None:
        upload_id = self._upload("ACES")
        failing = FailingVisionProvider(ProviderTimeoutError("tempo esgotado"))
        with patch("src.screenshot_parser.providers.get_provider", return_value=failing):
            resp = self.client.post(f"/api/screenshots/{upload_id}/extract")
        self.assertEqual(resp.status_code, 504)

    def test_provider_bad_response_maps_to_502(self) -> None:
        upload_id = self._upload("ACES")
        failing = FailingVisionProvider(ProviderResponseError("resposta invalida"))
        with patch("src.screenshot_parser.providers.get_provider", return_value=failing):
            resp = self.client.post(f"/api/screenshots/{upload_id}/extract")
        self.assertEqual(resp.status_code, 502)

    def test_unknown_upload_id_is_404(self) -> None:
        resp = self.client.post("/api/screenshots/does-not-exist/extract")
        self.assertEqual(resp.status_code, 404)

    def test_unknown_upload_id_on_get_extraction_is_404(self) -> None:
        resp = self.client.get("/api/screenshots/does-not-exist/extraction")
        self.assertEqual(resp.status_code, 404)

    def test_no_extraction_yet_is_404(self) -> None:
        upload_id = self._upload("ACES")
        resp = self.client.get(f"/api/screenshots/{upload_id}/extraction")
        self.assertEqual(resp.status_code, 404)


class TestExtractionPersistence(_ExtractionTestCase):
    def test_raw_extraction_is_persisted_and_never_overwritten(self) -> None:
        upload_id = self._upload("ACES")
        self._extract_with(upload_id, [
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="6+", decimal_odds=2.92),
        ])
        self._extract_with(upload_id, [
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="5+", decimal_odds=2.05),
        ])
        history = extraction_storage.list_raw_extractions(upload_id)
        self.assertEqual(len(history), 2)
        self.assertNotEqual(history[0].extraction_id, history[1].extraction_id)

    def test_get_extraction_returns_the_latest(self) -> None:
        upload_id = self._upload("ACES")
        self._extract_with(upload_id, [
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="6+", decimal_odds=2.92),
        ])
        self._extract_with(upload_id, [
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="5+", decimal_odds=2.05),
        ])
        resp = self.client.get(f"/api/screenshots/{upload_id}/extraction")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["markets"][0]["bookmaker_display"], "5+")

    def test_original_image_is_untouched_by_extraction(self) -> None:
        upload_id = self._upload("ACES")
        image_paths_before = list((self.tmp_path / "screenshots").rglob("*.png"))
        self.assertEqual(len(image_paths_before), 1)
        hash_before = hashlib.sha256(image_paths_before[0].read_bytes()).hexdigest()

        self._extract_with(upload_id, [
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="6+", decimal_odds=2.92),
        ])

        image_paths_after = list((self.tmp_path / "screenshots").rglob("*.png"))
        self.assertEqual(len(image_paths_after), 1)
        self.assertEqual(hashlib.sha256(image_paths_after[0].read_bytes()).hexdigest(), hash_before)


class TestConfirm(_ExtractionTestCase):
    def _confirm(self, upload_id: str, markets: list[dict]):
        return self.client.post(f"/api/screenshots/{upload_id}/confirm", json={"markets": markets})

    def test_confirm_without_correction(self) -> None:
        upload_id = self._upload("ACES")
        self._extract_with(upload_id, [
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="6+", decimal_odds=2.92),
        ])
        resp = self._confirm(upload_id, [
            {"market": "aces_player", "player": "Sebastian Baez", "bookmaker_display": "6+", "decimal_odds": 2.92},
        ])
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["corrected"])
        self.assertEqual(body["confirmed_by"], "local_user")
        self.assertEqual(body["markets"][0]["model_line"], 5.5)

    def test_confirm_with_manual_correction(self) -> None:
        upload_id = self._upload("ACES")
        self._extract_with(upload_id, [
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="6+", decimal_odds=2.92),
        ])
        # Usuario corrige a odd lida errado pela IA.
        resp = self._confirm(upload_id, [
            {"market": "aces_player", "player": "Sebastian Baez", "bookmaker_display": "6+", "decimal_odds": 3.10},
        ])
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["corrected"])
        self.assertEqual(body["markets"][0]["decimal_odds"], 3.10)

    def test_confirm_derives_model_line_from_display_not_client(self) -> None:
        upload_id = self._upload("ACES")
        resp = self._confirm(upload_id, [
            {"market": "aces_player", "player": "Sebastian Baez", "bookmaker_display": "8+", "decimal_odds": 4.5},
        ])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["markets"][0]["model_line"], 7.5)

    def test_confirm_blocks_on_invalid_odds(self) -> None:
        upload_id = self._upload("ACES")
        resp = self._confirm(upload_id, [
            {"market": "aces_player", "player": "Sebastian Baez", "bookmaker_display": "6+", "decimal_odds": 0.9},
        ])
        self.assertEqual(resp.status_code, 422)

    def test_confirm_blocks_on_unreadable_display(self) -> None:
        upload_id = self._upload("ACES")
        resp = self._confirm(upload_id, [
            {"market": "aces_player", "player": "Sebastian Baez", "bookmaker_display": "varios", "decimal_odds": 2.0},
        ])
        self.assertEqual(resp.status_code, 422)

    def test_confirm_allows_soft_warning_like_unrecognized_player(self) -> None:
        upload_id = self._upload("ACES")
        resp = self._confirm(upload_id, [
            {"market": "aces_player", "player": "Novak Djokovic", "bookmaker_display": "6+", "decimal_odds": 2.0},
        ])
        # Warning de contexto nao bloqueia -- usuario pode confirmar mesmo assim.
        self.assertEqual(resp.status_code, 200)
        self.assertIn("JOGADOR_NAO_RECONHECIDO", resp.json()["markets"][0]["warnings"])

    def test_confirm_unknown_upload_id_is_404(self) -> None:
        resp = self._confirm("does-not-exist", [
            {"market": "aces_player", "player": "A", "bookmaker_display": "6+", "decimal_odds": 2.0},
        ])
        self.assertEqual(resp.status_code, 404)

    def test_confirmed_extraction_is_persisted_separately_from_raw(self) -> None:
        upload_id = self._upload("ACES")
        self._extract_with(upload_id, [
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="6+", decimal_odds=2.92),
        ])
        self._confirm(upload_id, [
            {"market": "aces_player", "player": "Sebastian Baez", "bookmaker_display": "6+", "decimal_odds": 2.92},
        ])
        self.assertEqual(len(extraction_storage.list_raw_extractions(upload_id)), 1)
        self.assertEqual(len(extraction_storage.list_confirmed(upload_id)), 1)


if __name__ == "__main__":
    unittest.main()
