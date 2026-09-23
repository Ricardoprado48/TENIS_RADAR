"""Testes de integracao HTTP do LOTE C (GET /api/calendar,
docs/018_PWA_ARQUITETURA.md secao 9): rota registrada, contrato de
resposta (api/schemas/calendar.py), filtros de query, validacao 422 para
parametros ausentes, e ausencia de efeito colateral sobre data/raw.

O diretorio real de calendario (src/calendar/config.py CALENDAR_RAW_DIR) e
substituido por um diretorio temporario via mock.patch -- prova a costura
completa rota -> servico -> provider -> schema sem depender de nenhum
arquivo de calendario real estar presente no ambiente."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app

FIELDS = [
    "tour", "tournament", "round", "player_a_raw", "player_b_raw", "surface",
    "event_datetime_original", "event_timezone", "source_url", "collected_at",
]

ROW = {
    "tour": "ATP",
    "tournament": "Shanghai Masters",
    "round": "R32",
    "player_a_raw": "Novak Djokovic",
    "player_b_raw": "Carlos Alcaraz",
    "surface": "Hard",
    "event_datetime_original": "2026-09-23T14:00:00",
    "event_timezone": "Asia/Shanghai",
    "source_url": "https://example.com/shanghai",
    "collected_at": "2026-09-22T18:00:00Z",
}


class TestCalendarEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        path = self.tmp_path / "agenda_20260923.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerow(ROW)
        self._patcher = patch("src.calendar.config.CALENDAR_RAW_DIR", self.tmp_path)
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self._tmp.cleanup()

    def test_calendar_route_is_registered(self) -> None:
        paths = set(app.openapi()["paths"].keys())
        self.assertIn("/api/calendar", paths)

    def test_returns_matches_within_the_requested_range(self) -> None:
        resp = self.client.get(
            "/api/calendar",
            params={"date_from": "2026-09-23", "date_to": "2026-09-23"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body), 1)
        match = body[0]
        self.assertEqual(match["tour"], "ATP")
        self.assertEqual(match["tournament"], "Shanghai Masters")
        self.assertEqual(match["player_a"], "Novak Djokovic")
        self.assertEqual(match["event_datetime_sao_paulo"], "2026-09-23T03:00:00-03:00")
        self.assertIn("match_key", match)
        self.assertIn(match["status"], {"futuro", "proximo", "iniciado", "encerrado"})

    def test_date_range_outside_the_data_returns_empty_list(self) -> None:
        resp = self.client.get(
            "/api/calendar",
            params={"date_from": "2026-01-01", "date_to": "2026-01-02"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_tour_filter_is_applied(self) -> None:
        resp = self.client.get(
            "/api/calendar",
            params={"date_from": "2026-09-23", "date_to": "2026-09-23", "tour": "WTA"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_invalid_tour_is_rejected_with_422(self) -> None:
        resp = self.client.get(
            "/api/calendar",
            params={"date_from": "2026-09-23", "date_to": "2026-09-23", "tour": "ITF"},
        )
        self.assertEqual(resp.status_code, 422)

    def test_missing_required_date_params_returns_422(self) -> None:
        resp = self.client.get("/api/calendar")
        self.assertEqual(resp.status_code, 422)

    def test_response_matches_schema_field_set_exactly(self) -> None:
        resp = self.client.get(
            "/api/calendar",
            params={"date_from": "2026-09-23", "date_to": "2026-09-23"},
        )
        body = resp.json()[0]
        self.assertEqual(
            set(body.keys()),
            {
                "match_key", "tour", "tournament", "round", "surface",
                "player_a", "player_b", "event_datetime_original",
                "event_timezone", "event_datetime_utc",
                "event_datetime_sao_paulo", "status", "source_url",
                "collected_at",
            },
        )


class TestCalendarDoesNotTouchRawData(unittest.TestCase):
    """CLAUDE.md Sec.11: dado bruto nunca e sobrescrito -- so leitura."""

    def test_get_calendar_never_writes_to_the_raw_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            path = tmp_path / "agenda_20260923.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerow(ROW)
            before = path.read_text(encoding="utf-8")

            with patch("src.calendar.config.CALENDAR_RAW_DIR", tmp_path):
                client = TestClient(app)
                client.get(
                    "/api/calendar",
                    params={"date_from": "2026-09-23", "date_to": "2026-09-23"},
                )

            after = path.read_text(encoding="utf-8")
            self.assertEqual(before, after)
            self.assertEqual(list(tmp_path.iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
