"""Testes do LOTE H (docs/018 secao 22): `src.forward.build.register_opportunity`
/`is_registered` -- registro de UMA oportunidade especifica no Forward Test,
disparado pelo botao "Registrar no Forward Test" (nunca em lote, isso e
`register_day`). Reaproveita `_use_temp_dirs`/`_base_opportunity` de
`tests/test_forward.py` -- nenhuma fixture nova de fase 9/10/11 duplicada."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.forward import build
from src.forward import config as cfg
from src.forward import odds_snapshots as snaps
from src.forward import predictions as preds

from tests.test_forward import _base_opportunity, _use_temp_dirs


def _write_parquet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


class _RegisterOpportunityTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _use_temp_dirs(self)

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
        _write_parquet(cfg.PHASE10_OPPORTUNITIES_PATH, [self.opp])
        _write_parquet(cfg.PHASE9_OBSERVATIONS_PATH, [{
            "bookmaker": self.opp["bookmaker"], "match_id": self.opp["match_id"], "tour": self.opp["tour"],
            "market": self.opp["market"], "player": self.opp["player"], "side": self.opp["side"],
            "line": self.opp["line"], "collected_at": self.opp["collected_at"],
            "tournament": self.opp["tournament"], "opponent": self.opp["opponent"],
        }])

    def _key(self, **overrides) -> dict:
        opp = self.opp
        key = {
            "bookmaker": opp["bookmaker"], "tour": opp["tour"], "match_id": opp["match_id"],
            "market": opp["market"], "player": opp["player"], "side": opp["side"], "line": opp["line"],
            "decimal_odds": opp["decimal_odds"], "collected_at": opp["collected_at"],
        }
        key.update(overrides)
        return key


class TestRegisterOpportunity(_RegisterOpportunityTestCase):
    def test_register_new_opportunity(self) -> None:
        result = build.register_opportunity(self._key())
        self.assertEqual(result["status"], "registered")
        self.assertIsNotNone(result["prediction_id"])
        self.assertTrue(build.is_registered(result["prediction_id"]))
        self.assertEqual(len(preds.load_predictions()), 1)

    def test_registering_twice_is_idempotent_never_duplicates(self) -> None:
        first = build.register_opportunity(self._key())
        second = build.register_opportunity(self._key())
        self.assertEqual(first["prediction_id"], second["prediction_id"])
        self.assertEqual(second["status"], "already_registered")
        self.assertEqual(len(preds.load_predictions()), 1)

    def test_unknown_opportunity_is_not_found(self) -> None:
        result = build.register_opportunity(self._key(line=999.5))
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(len(preds.load_predictions()), 0)

    def test_is_registered_false_for_unknown_id(self) -> None:
        self.assertFalse(build.is_registered("PRED_0000000000000000"))

    def test_first_snapshot_is_recorded_on_registration(self) -> None:
        result = build.register_opportunity(self._key())
        snapshots = snaps.load_snapshots()
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots.iloc[0]["prediction_id"], result["prediction_id"])
        self.assertEqual(snapshots.iloc[0]["decimal_odds"], self.opp["decimal_odds"])

    def test_different_market_key_is_not_found(self) -> None:
        result = build.register_opportunity(self._key(market="double_faults_player"))
        self.assertEqual(result["status"], "not_found")


if __name__ == "__main__":
    unittest.main()
