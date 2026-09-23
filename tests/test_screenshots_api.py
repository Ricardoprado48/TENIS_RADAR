"""Testes de integracao HTTP do LOTE E (POST /api/screenshots,
docs/018_PWA_ARQUITETURA.md secao 9 + instrucoes do LOTE E): upload
multipart, validacao de formato/tamanho/campos obrigatorios, hash,
unicidade de upload_id, historico append-only e persistencia dos
metadados.

O diretorio real de armazenamento (src/screenshot_parser/config.py
SCREENSHOTS_RAW_DIR) e substituido por um diretorio temporario via
mock.patch, igual ao padrao ja usado em tests/test_calendar_api.py --
nenhum arquivo real e criado/removido do projeto.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from api.main import app

DEFAULT_MATCH_KEY = "atp-shanghai-masters-r32-novak-djokovic-carlos-alcaraz-2026-09-23"


def _image_bytes(fmt: str, size: tuple[int, int] = (20, 20)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color=(10, 20, 30)).save(buf, format=fmt)
    return buf.getvalue()


PNG_BYTES = _image_bytes("PNG")
JPEG_BYTES = _image_bytes("JPEG")
WEBP_BYTES = _image_bytes("WEBP")


class _ScreenshotUploadTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self._patcher = patch("src.screenshot_parser.config.SCREENSHOTS_RAW_DIR", self.tmp_path)
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self._tmp.cleanup()

    def _post(
        self,
        content: bytes | None,
        filename: str,
        content_type: str,
        match_key: str | None = DEFAULT_MATCH_KEY,
        tab_type: str | None = "ACES",
    ):
        data = {}
        if match_key is not None:
            data["match_key"] = match_key
        if tab_type is not None:
            data["tab_type"] = tab_type
        files = {"image": (filename, content, content_type)} if content is not None else None
        return self.client.post("/api/screenshots", data=data, files=files)


class TestRouteRegistered(_ScreenshotUploadTestCase):
    def test_route_is_registered(self) -> None:
        paths = set(app.openapi()["paths"].keys())
        self.assertIn("/api/screenshots", paths)


class TestValidUploads(_ScreenshotUploadTestCase):
    def test_png_upload_succeeds(self) -> None:
        resp = self._post(PNG_BYTES, "print.png", "image/png")
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["mime_type"], "image/png")
        self.assertEqual(body["tab_type"], "ACES")
        self.assertEqual(body["bookmaker"], "Betano")
        self.assertEqual(body["match_key"], DEFAULT_MATCH_KEY)
        self.assertEqual(body["file_size"], len(PNG_BYTES))
        self.assertIn("upload_id", body)
        self.assertIn("created_at", body)
        self.assertEqual(
            set(body.keys()),
            {"upload_id", "match_key", "tab_type", "bookmaker", "created_at", "mime_type", "file_size"},
        )

    def test_jpg_upload_succeeds(self) -> None:
        resp = self._post(JPEG_BYTES, "print.jpg", "image/jpeg")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["mime_type"], "image/jpeg")

    def test_webp_upload_succeeds(self) -> None:
        resp = self._post(WEBP_BYTES, "print.webp", "image/webp", tab_type="GAMES_TOTALS")
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["mime_type"], "image/webp")
        self.assertEqual(body["tab_type"], "GAMES_TOTALS")


class TestRejections(_ScreenshotUploadTestCase):
    def test_disallowed_format_is_rejected_even_with_image_extension(self) -> None:
        # Nao confiar so na extensao: bytes de texto puro nomeados "print.png".
        resp = self._post(b"isto nao e uma imagem de verdade", "print.png", "image/png")
        self.assertEqual(resp.status_code, 422)

    def test_empty_file_is_rejected(self) -> None:
        resp = self._post(b"", "print.png", "image/png")
        self.assertEqual(resp.status_code, 422)

    def test_file_over_size_limit_is_rejected(self) -> None:
        oversized = b"0" * (10 * 1024 * 1024 + 1)
        resp = self._post(oversized, "print.png", "image/png")
        self.assertEqual(resp.status_code, 422)

    def test_invalid_tab_type_is_rejected(self) -> None:
        resp = self._post(PNG_BYTES, "print.png", "image/png", tab_type="GAMES")
        self.assertEqual(resp.status_code, 422)

    def test_missing_match_key_is_rejected(self) -> None:
        resp = self._post(PNG_BYTES, "print.png", "image/png", match_key=None)
        self.assertEqual(resp.status_code, 422)

    def test_blank_match_key_is_rejected(self) -> None:
        resp = self._post(PNG_BYTES, "print.png", "image/png", match_key="   ")
        self.assertEqual(resp.status_code, 422)

    def test_missing_file_is_rejected(self) -> None:
        resp = self._post(None, "print.png", "image/png")
        self.assertEqual(resp.status_code, 422)

    def test_rejected_upload_writes_nothing_to_disk(self) -> None:
        self._post(b"nao e imagem", "print.png", "image/png")
        self.assertEqual(list(self.tmp_path.rglob("*")), [])


class TestAuditTrail(_ScreenshotUploadTestCase):
    def _sidecar_for(self, upload_id: str, tab_type: str) -> dict:
        matches = list(self.tmp_path.rglob(f"{upload_id}_{tab_type}.json"))
        self.assertEqual(len(matches), 1, f"esperava 1 sidecar, achou {len(matches)}")
        return json.loads(matches[0].read_text(encoding="utf-8"))

    def test_hash_is_created_and_matches_content(self) -> None:
        body = self._post(PNG_BYTES, "print.png", "image/png").json()
        sidecar = self._sidecar_for(body["upload_id"], "ACES")
        self.assertEqual(sidecar["sha256"], hashlib.sha256(PNG_BYTES).hexdigest())

    def test_upload_id_is_unique_across_uploads(self) -> None:
        first = self._post(PNG_BYTES, "print.png", "image/png").json()
        second = self._post(PNG_BYTES, "print.png", "image/png").json()
        self.assertNotEqual(first["upload_id"], second["upload_id"])

    def test_history_is_never_overwritten(self) -> None:
        first = self._post(PNG_BYTES, "print.png", "image/png").json()
        second = self._post(PNG_BYTES, "print.png", "image/png").json()

        images = list(self.tmp_path.rglob("*.png"))
        self.assertEqual(len(images), 2)
        stems = {p.stem for p in images}
        self.assertIn(f"{first['upload_id']}_ACES", stems)
        self.assertIn(f"{second['upload_id']}_ACES", stems)

    def test_metadata_is_persisted_with_expected_fields(self) -> None:
        body = self._post(PNG_BYTES, "print.png", "image/png", match_key=DEFAULT_MATCH_KEY).json()
        sidecar = self._sidecar_for(body["upload_id"], "ACES")

        self.assertEqual(sidecar["upload_id"], body["upload_id"])
        self.assertEqual(sidecar["match_key"], DEFAULT_MATCH_KEY)
        self.assertEqual(sidecar["tab_type"], "ACES")
        self.assertEqual(sidecar["bookmaker"], "Betano")
        self.assertEqual(sidecar["original_filename"], "print.png")
        self.assertEqual(sidecar["mime_type"], "image/png")
        self.assertEqual(sidecar["file_size"], len(PNG_BYTES))
        self.assertTrue(sidecar["stored_path"].startswith("bookmaker_screenshots/"))
        self.assertTrue(sidecar["stored_path"].endswith(f"{body['upload_id']}_ACES.png"))
        self.assertNotIn("\\", sidecar["stored_path"])  # nunca caminho estilo Windows
        self.assertIn("created_at", sidecar)


if __name__ == "__main__":
    unittest.main()
