"""Testes do LOTE G (docs/018_PWA_ARQUITETURA.md secao 14 + instrucoes do
LOTE G): `src.odds.screenshot_evaluation.evaluate_confirmed` -- o adapter
entre a leitura CONFIRMADA do LOTE F e o pipeline ja existente das Fases
9/10.

So as saidas (`data/outputs/phase9/`, `data/outputs/phase10/`) e os
diretorios do screenshot_parser sao redirecionados para um diretorio
temporario -- as ENTRADAS (`data/outputs/phase8/precos_por_linha.parquet`
etc.) continuam sendo as reais desta maquina (mesmo padrao aceito por
`tests/test_decision.py::TestBuildEndToEndWithRealData`), com `skipTest`
quando o arquivo nao existir, para a suite continuar portavel.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from PIL import Image

from src.decision import config as decision_cfg
from src.odds import config as odds_cfg
from src.odds import screenshot_evaluation as se
from src.screenshot_parser import config as sp_cfg
from src.screenshot_parser import extraction_storage
from src.screenshot_parser.models import ConfirmedExtraction, MatchContext, NormalizedMarket

MATCH_KEY = "atp-chengdu-open-r32-sebastian-baez-jenson-brooksby-2026-09-23"
CONTEXT = MatchContext(
    match_key=MATCH_KEY, tour="ATP", tournament="Chengdu Open",
    player_a="Sebastian Baez", player_b="Jenson Brooksby",
)


def _market(**overrides) -> NormalizedMarket:
    base = dict(
        market="aces_player", player="Sebastian Baez", bookmaker_display="6+",
        side="Over", model_line=5.5, decimal_odds=2.92, confidence=None,
        warnings=(), needs_confirmation=False,
    )
    base.update(overrides)
    return NormalizedMarket(**base)


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (20, 20), color=(10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


PNG_BYTES = _png_bytes()


def _confirmed(markets: list[NormalizedMarket], *, upload_id="up-1", extraction_id="ext-1") -> ConfirmedExtraction:
    return ConfirmedExtraction(
        extraction_id=extraction_id, upload_id=upload_id, match_key=MATCH_KEY,
        tab_type="ACES", confirmed_at=datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc),
        confirmed_by="local_user", corrected=False, markets=tuple(markets),
    )


class _EvaluationTestCase(unittest.TestCase):
    """Redireciona toda ESCRITA (screenshot_parser + Fase 9 + Fase 10) para
    um diretorio temporario. Nunca toca `data/outputs/phase8/` (leitura) ou
    qualquer arquivo real do projeto."""

    def setUp(self) -> None:
        if not odds_cfg.PHASE8_PRICES_PATH.exists():
            self.skipTest("data/outputs/phase8/precos_por_linha.parquet nao existe nesta maquina")

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)

        self._orig = {}
        for mod, attrs in [
            (sp_cfg, ["SCREENSHOTS_RAW_DIR", "EXTRACTED_RAW_DIR", "CONFIRMED_DIR"]),
            (odds_cfg, ["PHASE9_DIR", "ODDS_OBSERVED_PATH", "COMPARISON_PATH", "DAILY_CHECK_PATH", "SNAPSHOTS_HISTORY_PATH"]),
            (decision_cfg, ["PHASE9_COMPARISON_PATH", "PHASE10_DIR", "OPPORTUNITIES_PATH", "OPERATIONAL_RULES_PATH", "CLASSIFICATION_SUMMARY_PATH", "REJECTED_PATH", "PHASE10_SUMMARY_PATH"]),
        ]:
            for attr in attrs:
                self._orig[(mod, attr)] = getattr(mod, attr)

        sp_cfg.SCREENSHOTS_RAW_DIR = tmp / "screenshots"
        sp_cfg.EXTRACTED_RAW_DIR = tmp / "extracted"
        sp_cfg.CONFIRMED_DIR = tmp / "confirmed"

        odds_cfg.PHASE9_DIR = tmp / "phase9"
        odds_cfg.ODDS_OBSERVED_PATH = odds_cfg.PHASE9_DIR / "odds_observed.parquet"
        odds_cfg.COMPARISON_PATH = odds_cfg.PHASE9_DIR / "comparison_with_model.parquet"
        odds_cfg.DAILY_CHECK_PATH = odds_cfg.PHASE9_DIR / "daily_odds_check.csv"
        odds_cfg.SNAPSHOTS_HISTORY_PATH = odds_cfg.PHASE9_DIR / "snapshots_history.parquet"

        # decision/config.py define PHASE9_COMPARISON_PATH de forma
        # independente (mesmo caminho REAL por padrao) -- precisa apontar
        # para o MESMO tmp que odds_cfg.COMPARISON_PATH acima, senao a
        # Fase 10 nesta suite leria o parquet real (nao o que acabou de
        # ser escrito pela Fase 9 nesta chamada).
        decision_cfg.PHASE9_COMPARISON_PATH = odds_cfg.COMPARISON_PATH

        decision_cfg.PHASE10_DIR = tmp / "phase10"
        decision_cfg.OPPORTUNITIES_PATH = decision_cfg.PHASE10_DIR / "opportunities_evaluated.parquet"
        decision_cfg.OPERATIONAL_RULES_PATH = decision_cfg.PHASE10_DIR / "operational_rules.json"
        decision_cfg.CLASSIFICATION_SUMMARY_PATH = decision_cfg.PHASE10_DIR / "classification_summary.csv"
        decision_cfg.REJECTED_PATH = decision_cfg.PHASE10_DIR / "rejected_opportunities.csv"
        decision_cfg.PHASE10_SUMMARY_PATH = decision_cfg.PHASE10_DIR / "phase10_summary.json"

        self.addCleanup(self._restore)

        self._context_patch = patch("src.screenshot_parser.extractor._build_match_context", return_value=CONTEXT)
        self._context_patch.start()
        self.addCleanup(self._context_patch.stop)

    def _restore(self) -> None:
        for (mod, attr), value in self._orig.items():
            setattr(mod, attr, value)

    def _save_confirmed(self, markets: list[NormalizedMarket], **kwargs) -> ConfirmedExtraction:
        # upload precisa "existir" para `UploadNotFoundError` nao disparar.
        from src.screenshot_parser import storage as sp_storage

        confirmed = _confirmed(markets, **kwargs)
        sp_cfg.SCREENSHOTS_RAW_DIR.mkdir(parents=True, exist_ok=True)
        record = sp_storage.save_screenshot(
            content=PNG_BYTES,
            original_filename="print.png", match_key=MATCH_KEY, tab_type="ACES",
        )
        confirmed = ConfirmedExtraction(
            extraction_id=confirmed.extraction_id, upload_id=record.upload_id,
            match_key=MATCH_KEY, tab_type="ACES", confirmed_at=confirmed.confirmed_at,
            confirmed_by=confirmed.confirmed_by, corrected=confirmed.corrected,
            markets=confirmed.markets,
        )
        extraction_storage.save_confirmed(confirmed)
        return confirmed


class TestUnsupportedMarket(_EvaluationTestCase):
    def test_total_games_is_not_evaluated_by_model(self) -> None:
        confirmed = self._save_confirmed([
            _market(market="total_games", player=None, side="Over", model_line=22.5, bookmaker_display="Mais de 22.5", decimal_odds=1.85),
        ])
        result = se.evaluate_confirmed(confirmed.upload_id)
        self.assertEqual(len(result["results"]), 1)
        r = result["results"][0]
        self.assertEqual(r["evaluation_label"], se.EVAL_SEM_MODELO)
        self.assertEqual(r["evaluation_message"], se.MSG_MERCADO_NAO_MODELADO)
        self.assertIsNone(r["decision_state"])
        self.assertIsNone(r["error"])
        # nao deve ter sido registrado no ledger de odds (nada a avaliar).
        self.assertFalse(odds_cfg.ODDS_OBSERVED_PATH.exists())


class TestAcesPlayerMatched(_EvaluationTestCase):
    def test_matched_line_is_classified_by_existing_pipeline(self) -> None:
        confirmed = self._save_confirmed([
            _market(market="aces_player", player="Sebastian Baez", side="Over", model_line=5.5, bookmaker_display="6+", decimal_odds=2.92),
        ])
        result = se.evaluate_confirmed(confirmed.upload_id)

        self.assertEqual(result["upload_id"], confirmed.upload_id)
        self.assertEqual(result["match_key"], MATCH_KEY)
        self.assertIsNotNone(result["historical_data_cutoff"])
        self.assertIn("Base historica atualizada", result["staleness_warning"])

        r = result["results"][0]
        self.assertEqual(r["market"], "aces_player")
        self.assertEqual(r["bookmaker_odds"], 2.92)
        self.assertIn(r["decision_state"], decision_cfg.STATES_ORDER)
        self.assertIn(r["evaluation_label"], (se.EVAL_PASSOU, se.EVAL_OBSERVAR, se.EVAL_NAO_PASSOU))
        self.assertIsNotNone(r["model_probability"])
        self.assertIsNotNone(r["fair_odds"])
        # piso de aces_player = ATINGE_EDGE_3 (3%) -- odd_minima_3pct precisa
        # existir e ser maior que a fair_odds (edge minimo exigido > 0).
        self.assertIsNotNone(r["minimum_odds"])
        self.assertGreater(r["minimum_odds"], r["fair_odds"])
        self.assertIsNotNone(r["staleness_status"])
        self.assertIn(r["staleness_status"], (decision_cfg.STALENESS_ATUAL, decision_cfg.STALENESS_MODERADO, decision_cfg.STALENESS_MUITO_DEFASADO))
        self.assertIsNotNone(r["technical"])
        self.assertTrue(r["technical"]["matched"])

        # persistencia real via Fase 9/10 (nenhuma segunda fonte de verdade).
        self.assertTrue(odds_cfg.ODDS_OBSERVED_PATH.exists())
        obs = pd.read_parquet(odds_cfg.ODDS_OBSERVED_PATH)
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs.iloc[0]["source_method"], "screenshot_confirmed")
        self.assertTrue(decision_cfg.OPPORTUNITIES_PATH.exists())

    def test_high_odds_reaches_passou_do_limite(self) -> None:
        # odd bem acima da odd minima por edge (fair_odds ~4.09) -> edge
        # positivo suficiente para atingir o piso de aces_player (3%).
        confirmed = self._save_confirmed([
            _market(market="aces_player", player="Sebastian Baez", side="Over", model_line=5.5, bookmaker_display="6+", decimal_odds=5.0),
        ])
        result = se.evaluate_confirmed(confirmed.upload_id)
        r = result["results"][0]
        self.assertEqual(r["evaluation_label"], se.EVAL_PASSOU)
        self.assertIn(r["decision_state"], (
            decision_cfg.STATE_CANDIDATO_FRACO, decision_cfg.STATE_CANDIDATO, decision_cfg.STATE_CANDIDATO_FORTE,
        ))

    def test_unmatched_line_is_descartar(self) -> None:
        confirmed = self._save_confirmed([
            _market(market="aces_player", player="Sebastian Baez", side="Over", model_line=100.5, bookmaker_display="101+", decimal_odds=50.0),
        ])
        result = se.evaluate_confirmed(confirmed.upload_id)
        r = result["results"][0]
        self.assertEqual(r["decision_state"], decision_cfg.STATE_DESCARTAR)
        self.assertEqual(r["evaluation_label"], se.EVAL_NAO_PASSOU)
        self.assertFalse(r["technical"]["matched"])
        self.assertIsNotNone(r["technical"]["match_reason"])


class TestTotalAcesMatchAnchorsToPlayerA(_EvaluationTestCase):
    def test_player_none_resolves_via_calendar_context(self) -> None:
        confirmed = self._save_confirmed([
            _market(market="total_aces_match", player=None, side="Over", model_line=13.5, bookmaker_display="14+", decimal_odds=5.48),
        ])
        result = se.evaluate_confirmed(confirmed.upload_id)
        r = result["results"][0]
        self.assertIsNone(r["player"])  # devolvido tal como o print mostrou
        self.assertIsNotNone(r["model_probability"])
        self.assertTrue(r["technical"]["matched"])

        obs = pd.read_parquet(odds_cfg.ODDS_OBSERVED_PATH)
        self.assertEqual(obs.iloc[0]["player"], "Sebastian Baez")
        # `opponent` persistido e o nome RESOLVIDO pelo radar (Fase 9,
        # `match.resolved_opponent_name`), que ja normaliza para minusculas
        # -- comportamento existente de `src.odds.build`, nao alterado aqui.
        self.assertEqual(obs.iloc[0]["opponent"], "jenson brooksby")


class TestNoConfirmedOrMissingUpload(_EvaluationTestCase):
    def test_upload_not_found(self) -> None:
        with self.assertRaises(se.UploadNotFoundError):
            se.evaluate_confirmed("does-not-exist")

    def test_upload_exists_but_not_confirmed(self) -> None:
        from src.screenshot_parser import storage as sp_storage

        sp_cfg.SCREENSHOTS_RAW_DIR.mkdir(parents=True, exist_ok=True)
        record = sp_storage.save_screenshot(
            content=PNG_BYTES,
            original_filename="print.png", match_key=MATCH_KEY, tab_type="ACES",
        )
        with self.assertRaises(se.NoConfirmedExtractionError):
            se.evaluate_confirmed(record.upload_id)


class TestMatchContextUnavailable(_EvaluationTestCase):
    def test_missing_calendar_context_blocks_evaluation(self) -> None:
        self._context_patch.stop()
        try:
            with patch("src.screenshot_parser.extractor._build_match_context", return_value=None):
                confirmed = self._save_confirmed([
                    _market(market="aces_player", player="Sebastian Baez", side="Over", model_line=5.5, bookmaker_display="6+", decimal_odds=2.92),
                ])
                with self.assertRaises(se.MatchContextUnavailableError):
                    se.evaluate_confirmed(confirmed.upload_id)
        finally:
            self._context_patch.start()


class TestNoParallelRecalculation(_EvaluationTestCase):
    def test_module_never_imports_pricing_formulas_directly(self) -> None:
        import inspect

        source = inspect.getsource(se)
        self.assertNotIn("implied_probability(", source)
        self.assertNotIn("minimum_acceptable_odds(", source)
        self.assertNotIn("from src.pricing", source)


if __name__ == "__main__":
    unittest.main()
