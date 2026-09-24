"""Testes de materialização snapshot Live Tennis -> CSV da Fase 8.

Não acessam rede e usam o validador real src/radar/sources.py.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.radar.live_tennis_phase8 import (
    LiveTennisPhase8MaterializationError,
    materialize_phase8_csv,
    snapshot_to_phase8_dataframe,
)
from src.radar.sources import load_raw_matches


def _match(match_id: int, tour: str, name_a: str, name_b: str):
    return {
        "id": match_id,
        "status": "upcoming",
        "tour": tour.lower(),
        "tournament": "Evento Teste",
        "surface": "hard",
        "round_code": "QF",
        "scheduled_time": "2026-09-25T03:00:00Z",
        "tournament_id": "T1",
        "players": {
            "p1": {"name": name_a},
            "p2": {"name": name_b},
        },
    }


def _fixture(match_id: int, fixture_id: int):
    return {
        "id": fixture_id,
        "match_id": match_id,
        "event_date": "2026-09-25",
        "round_code": "QF",
    }


def _payload():
    return {
        "schema_version": 1,
        "collected_at": "2026-09-24T18:41:32Z",
        "tours": {
            "ATP": {
                "upcoming": [_match(1, "ATP", "Player ATP A", "Player ATP B")],
                "fixtures": [_fixture(1, 101)],
            },
            "WTA": {
                "upcoming": [_match(2, "WTA", "Player WTA A", "Player WTA B")],
                "fixtures": [_fixture(2, 202)],
            },
        },
    }


class TestLiveTennisPhase8Materialization(unittest.TestCase):
    def _write_snapshot(self, root: Path, payload=None) -> Path:
        path = root / "snapshot.json"
        path.write_text(
            json.dumps(payload if payload is not None else _payload()),
            encoding="utf-8",
        )
        return path

    def test_combines_atp_and_wta_into_phase8_dataframe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_snapshot(Path(tmp))
            df = snapshot_to_phase8_dataframe(path)

        self.assertEqual(len(df), 2)
        self.assertEqual(set(df["tour"]), {"ATP", "WTA"})
        self.assertEqual(set(df["match_date"]), {"2026-09-25"})

    def test_materialized_csv_passes_existing_phase8_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = self._write_snapshot(root)
            output_dir = root / "phase8"

            csv_path = materialize_phase8_csv(snapshot, output_dir=output_dir)
            loaded = load_raw_matches(csv_path)

            self.assertEqual(csv_path.name, "partidas_futuras_20260924.csv")
            self.assertEqual(len(loaded), 2)
            self.assertTrue(
                {
                    "source_url",
                    "collected_at",
                    "tour",
                    "tournament",
                    "surface",
                    "match_date",
                    "round",
                    "player_a_raw",
                    "player_b_raw",
                }.issubset(loaded.columns)
            )

    def test_daily_csv_is_replaced_atomically_by_selected_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "phase8"

            first = _payload()
            first_path = self._write_snapshot(root, first)
            csv_path = materialize_phase8_csv(first_path, output_dir=output_dir)

            second = _payload()
            second["tours"]["WTA"]["upcoming"] = []
            second["tours"]["WTA"]["fixtures"] = []
            second_path = root / "snapshot2.json"
            second_path.write_text(json.dumps(second), encoding="utf-8")

            same_csv = materialize_phase8_csv(second_path, output_dir=output_dir)
            loaded = load_raw_matches(same_csv)

            self.assertEqual(same_csv, csv_path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded.iloc[0]["tour"], "ATP")

    def test_rejects_unsupported_snapshot_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = _payload()
            bad["schema_version"] = 999
            path = self._write_snapshot(root, bad)

            with self.assertRaisesRegex(
                LiveTennisPhase8MaterializationError,
                "schema_version",
            ):
                snapshot_to_phase8_dataframe(path)


if __name__ == "__main__":
    unittest.main()
