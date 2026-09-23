"""Testes unitarios do LOTE F (docs/018_PWA_ARQUITETURA.md secao 7 e
instrucoes do LOTE F): mapping.py, validator.py e anthropic_provider.py.

Nenhuma chamada real de IA -- `TestAnthropicVisionProvider` substitui
`requests.post` por um mock (pedido explicito: "nao depender de chamada
real de IA para a suite").
"""

from __future__ import annotations

import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from PIL import Image

from src.screenshot_parser import mapping, providers, validator
from src.screenshot_parser.anthropic_provider import AnthropicVisionProvider
from src.screenshot_parser.models import MatchContext, RawReading
from src.screenshot_parser.providers import (
    ExtractionContext,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)


class TestMappingAces(unittest.TestCase):
    def test_x_plus_maps_to_x_minus_half_over(self) -> None:
        self.assertEqual(mapping.map_aces_display("6+"), (5.5, "Over"))
        self.assertEqual(mapping.map_aces_display("10+"), (9.5, "Over"))
        self.assertEqual(mapping.map_aces_display("3+"), (2.5, "Over"))

    def test_whitespace_is_tolerated(self) -> None:
        self.assertEqual(mapping.map_aces_display(" 6+ "), (5.5, "Over"))

    def test_zero_target_is_rejected(self) -> None:
        with self.assertRaises(mapping.MappingError):
            mapping.map_aces_display("0+")

    def test_unrecognized_format_is_rejected(self) -> None:
        with self.assertRaises(mapping.MappingError):
            mapping.map_aces_display("Mais de 6")


class TestMappingGamesTotals(unittest.TestCase):
    def test_mais_de_maps_to_over(self) -> None:
        self.assertEqual(mapping.map_games_total_display("Mais de 22.5"), (22.5, "Over"))

    def test_menos_de_maps_to_under(self) -> None:
        self.assertEqual(mapping.map_games_total_display("Menos de 22.5"), (22.5, "Under"))

    def test_comma_decimal_separator_is_accepted(self) -> None:
        self.assertEqual(mapping.map_games_total_display("Mais de 22,5"), (22.5, "Over"))

    def test_case_insensitive(self) -> None:
        self.assertEqual(mapping.map_games_total_display("mais DE 22.5"), (22.5, "Over"))

    def test_unrecognized_format_is_rejected(self) -> None:
        with self.assertRaises(mapping.MappingError):
            mapping.map_games_total_display("6+")


class TestDeriveLineAndSide(unittest.TestCase):
    def test_dispatches_by_market(self) -> None:
        self.assertEqual(mapping.derive_line_and_side("aces_player", "6+"), (5.5, "Over"))
        self.assertEqual(mapping.derive_line_and_side("total_aces_match", "12+"), (11.5, "Over"))
        self.assertEqual(mapping.derive_line_and_side("total_games", "Mais de 22.5"), (22.5, "Over"))

    def test_unsupported_market_is_rejected(self) -> None:
        with self.assertRaises(mapping.MappingError):
            mapping.derive_line_and_side("double_faults_player", "6+")


_CONTEXT = MatchContext(
    match_key="k", tour="ATP", tournament="T", player_a="Sebastian Baez", player_b="Jenson Brooksby"
)


class TestValidatorAces(unittest.TestCase):
    def test_valid_block_has_no_warnings(self) -> None:
        readings = [
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="3+", decimal_odds=1.21),
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="4+", decimal_odds=1.52),
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="5+", decimal_odds=2.05),
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="6+", decimal_odds=2.92),
        ]
        markets = validator.validate_and_normalize(readings, _CONTEXT)
        self.assertTrue(all(not m.warnings for m in markets))
        self.assertEqual(validator.determine_status(markets), "AUTO_VALIDATED")

    def test_total_aces_match_valid(self) -> None:
        readings = [RawReading(market="total_aces_match", player=None, bookmaker_display="12+", decimal_odds=2.40)]
        markets = validator.validate_and_normalize(readings)
        self.assertEqual(markets[0].model_line, 11.5)
        self.assertEqual(markets[0].side, "Over")
        self.assertFalse(markets[0].needs_confirmation)

    def test_non_monotonic_odds_warns_without_discarding(self) -> None:
        readings = [
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="3+", decimal_odds=1.21),
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="4+", decimal_odds=1.52),
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="5+", decimal_odds=7.05),
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="6+", decimal_odds=2.92),
        ]
        markets = validator.validate_and_normalize(readings, _CONTEXT)
        self.assertEqual(len(markets), 4)
        self.assertIn(validator.WARN_ODDS_NON_MONOTONIC, markets[2].warnings)
        self.assertIn(validator.WARN_ODDS_NON_MONOTONIC, markets[3].warnings)
        self.assertEqual(validator.determine_status(markets), "NEEDS_CONFIRMATION")
        # Warning de consistencia nao e um erro estrutural -- nao bloqueia confirmacao.
        self.assertFalse(validator.is_structural_error(markets[2]))

    def test_invalid_player_is_flagged(self) -> None:
        readings = [RawReading(market="aces_player", player="Novak Djokovic", bookmaker_display="6+", decimal_odds=2.0)]
        markets = validator.validate_and_normalize(readings, _CONTEXT)
        self.assertIn(validator.WARN_JOGADOR_NAO_RECONHECIDO, markets[0].warnings)
        self.assertFalse(validator.is_structural_error(markets[0]))

    def test_odd_at_or_below_one_is_structural_error(self) -> None:
        readings = [RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="6+", decimal_odds=1.0)]
        markets = validator.validate_and_normalize(readings, _CONTEXT)
        self.assertIn(validator.WARN_ODD_INVALIDA, markets[0].warnings)
        self.assertTrue(validator.is_structural_error(markets[0]))

    def test_unreadable_display_is_structural_error(self) -> None:
        readings = [RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="varios", decimal_odds=2.0)]
        markets = validator.validate_and_normalize(readings, _CONTEXT)
        self.assertIn(validator.WARN_FORMATO_ILEGIVEL, markets[0].warnings)
        self.assertIsNone(markets[0].model_line)
        self.assertTrue(validator.is_structural_error(markets[0]))

    def test_duplicate_combination_is_flagged(self) -> None:
        readings = [
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="6+", decimal_odds=2.0),
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="6+", decimal_odds=2.0),
        ]
        markets = validator.validate_and_normalize(readings, _CONTEXT)
        self.assertTrue(all(validator.WARN_LEITURA_DUPLICADA in m.warnings for m in markets))
        self.assertFalse(any(validator.is_structural_error(m) for m in markets))

    def test_non_increasing_lines_are_flagged(self) -> None:
        readings = [
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="6+", decimal_odds=2.92),
            RawReading(market="aces_player", player="Sebastian Baez", bookmaker_display="3+", decimal_odds=1.21),
        ]
        markets = validator.validate_and_normalize(readings, _CONTEXT)
        self.assertTrue(all(validator.WARN_LINHAS_NAO_CRESCENTES in m.warnings for m in markets))


class TestValidatorGames(unittest.TestCase):
    def test_valid_over_under_pair_has_no_warnings(self) -> None:
        readings = [
            RawReading(market="total_games", player=None, bookmaker_display="Mais de 22.5", decimal_odds=1.85),
            RawReading(market="total_games", player=None, bookmaker_display="Menos de 22.5", decimal_odds=1.85),
        ]
        markets = validator.validate_and_normalize(readings)
        self.assertTrue(all(not m.warnings for m in markets))
        self.assertEqual(validator.determine_status(markets), "AUTO_VALIDATED")

    def test_unpaired_line_is_flagged(self) -> None:
        readings = [RawReading(market="total_games", player=None, bookmaker_display="Mais de 22.5", decimal_odds=1.85)]
        markets = validator.validate_and_normalize(readings)
        self.assertIn(validator.WARN_LINHA_SEM_PAR_OVER_UNDER, markets[0].warnings)
        self.assertFalse(validator.is_structural_error(markets[0]))

    def test_odds_trend_is_a_soft_warning(self) -> None:
        readings = [
            RawReading(market="total_games", player=None, bookmaker_display="Mais de 20.5", decimal_odds=1.90),
            RawReading(market="total_games", player=None, bookmaker_display="Menos de 20.5", decimal_odds=1.80),
            RawReading(market="total_games", player=None, bookmaker_display="Mais de 22.5", decimal_odds=1.50),
            RawReading(market="total_games", player=None, bookmaker_display="Menos de 22.5", decimal_odds=2.50),
        ]
        markets = validator.validate_and_normalize(readings)
        over_22 = next(m for m in markets if m.model_line == 22.5 and m.side == "Over")
        under_22 = next(m for m in markets if m.model_line == 22.5 and m.side == "Under")
        self.assertIn(validator.WARN_GAMES_ODDS_TENDENCIA_ATIPICA, over_22.warnings)
        self.assertIn(validator.WARN_GAMES_ODDS_TENDENCIA_ATIPICA, under_22.warnings)
        self.assertFalse(validator.is_structural_error(over_22))


class TestValidatorEmpty(unittest.TestCase):
    def test_no_readings_needs_confirmation(self) -> None:
        self.assertEqual(validator.determine_status([]), "NEEDS_CONFIRMATION")


class TestGetProvider(unittest.TestCase):
    def test_default_provider_is_anthropic(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("TENNIS_RADAR_VISION_PROVIDER", None)
            provider = providers.get_provider()
        self.assertEqual(provider.name, "anthropic")

    def test_unknown_provider_name_raises_unavailable(self) -> None:
        with self.assertRaises(ProviderUnavailableError):
            providers.get_provider("not-a-real-provider")

    def test_fake_and_failing_cannot_be_resolved_by_name(self) -> None:
        with self.assertRaises(ProviderUnavailableError):
            providers.get_provider("fake")
        with self.assertRaises(ProviderUnavailableError):
            providers.get_provider("failing")


_tmp_dir = tempfile.TemporaryDirectory()


def _png_path() -> Path:
    path = Path(_tmp_dir.name) / "sample.png"
    if not path.exists():
        buf = BytesIO()
        Image.new("RGB", (10, 10)).save(buf, format="PNG")
        path.write_bytes(buf.getvalue())
    return path


def _fake_response(status_code: int, json_body: dict | None = None, text: str = "") -> Mock:
    resp = Mock()
    resp.status_code = status_code
    resp.text = text
    if json_body is not None:
        resp.json.return_value = json_body
    else:
        resp.json.side_effect = ValueError("no json")
    return resp


class TestAnthropicVisionProvider(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patcher = patch.dict(
            "os.environ",
            {"ANTHROPIC_API_KEY": "test-key", "TENNIS_RADAR_VISION_MODEL": "test-model"},
        )
        self._env_patcher.start()
        self.addCleanup(self._env_patcher.stop)

    def _extract(self, image_path):
        provider = AnthropicVisionProvider()
        context = ExtractionContext(match_context=_CONTEXT, tab_type="ACES")
        return provider.extract(image_path, context)

    def test_missing_api_key_raises_unavailable(self) -> None:
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            provider = AnthropicVisionProvider()
            with self.assertRaises(ProviderUnavailableError):
                provider.extract(_png_path(), ExtractionContext(match_context=None, tab_type="ACES"))

    def test_missing_model_raises_unavailable(self) -> None:
        with patch.dict("os.environ", {"TENNIS_RADAR_VISION_MODEL": ""}):
            provider = AnthropicVisionProvider()
            with self.assertRaises(ProviderUnavailableError):
                provider.extract(_png_path(), ExtractionContext(match_context=None, tab_type="ACES"))

    def test_timeout_is_mapped(self) -> None:
        with patch("requests.post", side_effect=requests.Timeout()):
            with self.assertRaises(ProviderTimeoutError):
                self._extract(_png_path())

    def test_connection_error_is_mapped_to_unavailable(self) -> None:
        with patch("requests.post", side_effect=requests.ConnectionError()):
            with self.assertRaises(ProviderUnavailableError):
                self._extract(_png_path())

    def test_auth_error_is_mapped_to_unavailable(self) -> None:
        with patch("requests.post", return_value=_fake_response(401)):
            with self.assertRaises(ProviderUnavailableError):
                self._extract(_png_path())

    def test_server_error_is_mapped_to_unavailable(self) -> None:
        with patch("requests.post", return_value=_fake_response(500)):
            with self.assertRaises(ProviderUnavailableError):
                self._extract(_png_path())

    def test_non_json_body_is_response_error(self) -> None:
        body = {"content": [{"type": "text", "text": "isto nao e json"}]}
        with patch("requests.post", return_value=_fake_response(200, body)):
            with self.assertRaises(ProviderResponseError):
                self._extract(_png_path())

    def test_valid_response_is_parsed_into_readings(self) -> None:
        payload = [
            {"market": "aces_player", "player": "Sebastian Baez", "bookmaker_display": "6+", "decimal_odds": 2.92, "source_confidence": 0.9},
        ]
        body = {"content": [{"type": "text", "text": json.dumps(payload)}]}
        with patch("requests.post", return_value=_fake_response(200, body)):
            result = self._extract(_png_path())
        self.assertEqual(len(result.readings), 1)
        self.assertEqual(result.readings[0].bookmaker_display, "6+")
        self.assertEqual(result.readings[0].source_confidence, 0.9)
        self.assertEqual(result.model, "test-model")

    def test_incomplete_items_are_skipped_not_invented(self) -> None:
        payload = [
            {"market": "aces_player", "bookmaker_display": "6+"},  # falta decimal_odds
            {"market": "aces_player", "player": "Sebastian Baez", "bookmaker_display": "6+", "decimal_odds": 2.92},
        ]
        body = {"content": [{"type": "text", "text": json.dumps(payload)}]}
        with patch("requests.post", return_value=_fake_response(200, body)):
            result = self._extract(_png_path())
        self.assertEqual(len(result.readings), 1)

    def test_markdown_fenced_json_is_accepted(self) -> None:
        payload = [{"market": "total_games", "player": None, "bookmaker_display": "Mais de 22.5", "decimal_odds": 1.85}]
        text = "```json\n" + json.dumps(payload) + "\n```"
        body = {"content": [{"type": "text", "text": text}]}
        with patch("requests.post", return_value=_fake_response(200, body)):
            result = self._extract(_png_path())
        self.assertEqual(len(result.readings), 1)


if __name__ == "__main__":
    unittest.main()
