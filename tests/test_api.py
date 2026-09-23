"""Testes do LOTE A (fundacao FastAPI, docs/018_PWA_ARQUITETURA.md):
inicializacao do app, /api/health, /api/info, configuracao de CORS restrita
aos hosts locais do Vite, e ausencia de efeitos colaterais sobre o motor
estatistico (Fases 0-11) so por a API existir/responder."""

from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from api.config import Settings, get_settings
from api.main import app
from src.forward import config as forward_cfg
from src.odds import config as odds_cfg

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_OUTPUTS = PROJECT_ROOT / "data" / "outputs"


def _snapshot_outputs() -> dict[str, float]:
    """Mapa relpath -> mtime de tudo em data/outputs, para provar que a API
    nao escreve/altera nenhuma saida historica do motor (CLAUDE.md Sec.11)."""
    if not DATA_OUTPUTS.exists():
        return {}
    return {
        str(p.relative_to(DATA_OUTPUTS)): p.stat().st_mtime
        for p in DATA_OUTPUTS.rglob("*")
        if p.is_file()
    }


class TestHealthEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health_returns_ok_status_and_app_name(self) -> None:
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["app"], "Tennis Radar")

    def test_health_is_get_only(self) -> None:
        resp = self.client.post("/api/health")
        self.assertEqual(resp.status_code, 405)


class TestInfoEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_info_returns_required_metadata_fields(self) -> None:
        resp = self.client.get("/api/info")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(set(body.keys()), {
            "app", "api_version", "timezone", "default_bookmaker",
            "historical_data_cutoff", "forward_version_id",
        })

    def test_info_reuses_existing_engine_metadata_not_invented(self) -> None:
        """default_bookmaker e forward_version_id devem vir literalmente de
        src/odds/config.py e src/forward/config.py -- nunca redefinidos em
        api/ (docs/018 secao 4.4/11)."""
        resp = self.client.get("/api/info").json()
        self.assertEqual(resp["default_bookmaker"], odds_cfg.DEFAULT_BOOKMAKER)
        self.assertEqual(resp["forward_version_id"], forward_cfg.FORWARD_VERSION_ID)

    def test_info_default_timezone_is_sao_paulo(self) -> None:
        resp = self.client.get("/api/info").json()
        self.assertEqual(resp["timezone"], "America/Sao_Paulo")

    def test_info_historical_data_cutoff_is_null_or_valid_iso_date(self) -> None:
        """Nunca um valor inventado: ou None (base indisponivel no
        ambiente) ou uma data ISO valida vinda de dados reais."""
        resp = self.client.get("/api/info").json()
        cutoff = resp["historical_data_cutoff"]
        if cutoff is not None:
            date.fromisoformat(cutoff)  # nao levanta se for uma data valida


class TestCorsConfiguration(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_allowed_vite_origin_is_echoed_back(self) -> None:
        resp = self.client.get(
            "/api/health", headers={"Origin": "http://localhost:5173"}
        )
        self.assertEqual(
            resp.headers.get("access-control-allow-origin"), "http://localhost:5173"
        )

    def test_arbitrary_external_origin_is_not_allowed(self) -> None:
        resp = self.client.get(
            "/api/health", headers={"Origin": "https://example.com"}
        )
        self.assertNotEqual(
            resp.headers.get("access-control-allow-origin"), "https://example.com"
        )

    def test_settings_never_default_to_wildcard_or_public_bind(self) -> None:
        settings = get_settings()
        self.assertNotIn("*", settings.allowed_origins)
        self.assertEqual(settings.host, "127.0.0.1")


class TestAppInitialization(unittest.TestCase):
    def test_app_metadata_matches_settings(self) -> None:
        settings: Settings = get_settings()
        self.assertEqual(app.title, settings.app_name)
        self.assertEqual(app.version, settings.api_version)

    def test_expected_routes_are_registered(self) -> None:
        paths = set(app.openapi()["paths"].keys())
        self.assertIn("/api/health", paths)
        self.assertIn("/api/info", paths)

    def test_unhandled_exception_returns_generic_500_without_leaking_detail(self) -> None:
        from fastapi import APIRouter

        broken_app = app
        # rota temporaria isolada so para este teste, nao afeta as rotas reais
        temp_router = APIRouter()

        @temp_router.get("/api/_test_only_boom")
        def boom():
            raise RuntimeError("detalhe interno que nao deve vazar")

        broken_app.include_router(temp_router)
        client = TestClient(broken_app, raise_server_exceptions=False)
        resp = client.get("/api/_test_only_boom")
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json(), {"detail": "Erro interno inesperado."})
        self.assertNotIn("detalhe interno", resp.text)


class TestNoSideEffectsOnExistingEngine(unittest.TestCase):
    """Garante que subir a API e responder health/info nao escreve, apaga
    ou modifica nenhuma saida ja congelada das Fases 0-11 (CLAUDE.md Sec.11:
    dados brutos e saidas nunca sao sobrescritos por acidente)."""

    def test_health_and_info_do_not_touch_data_outputs(self) -> None:
        before = _snapshot_outputs()
        client = TestClient(app)
        client.get("/api/health")
        client.get("/api/info")
        after = _snapshot_outputs()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
