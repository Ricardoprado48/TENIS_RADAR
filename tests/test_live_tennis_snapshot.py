"""Testes do snapshot bruto Live Tennis.

Não acessam a rede nem consomem quota.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.radar.live_tennis_snapshot import collect_live_tennis_snapshot


class _FakeClient:
    def list_upcoming_singles(self, tour: str):
        return [
            {
                "id": 100 if tour == "ATP" else 200,
                "status": "upcoming",
                "tour": tour.lower(),
            }
        ]

    def list_fixtures_singles(self, tour: str):
        return [
            {
                "id": 300 if tour == "ATP" else 400,
                "match_id": 100 if tour == "ATP" else 200,
                "event_date": "2026-09-25",
            }
        ]


class TestLiveTennisSnapshot(unittest.TestCase):
    def test_writes_immutable_timestamped_snapshot_without_secret(self):
        collected = datetime(2026, 9, 24, 18, 30, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as tmp:
            path = collect_live_tennis_snapshot(
                _FakeClient(),
                output_dir=tmp,
                collected_at=collected,
            )

            self.assertEqual(path.name, "live_tennis_20260924T183000Z.json")
            payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["collected_at"], "2026-09-24T18:30:00Z")
            self.assertEqual(payload["tours"]["ATP"]["upcoming"][0]["id"], 100)
            self.assertEqual(payload["tours"]["WTA"]["fixtures"][0]["match_id"], 200)

            serialized = path.read_text(encoding="utf-8")
            self.assertNotIn("api_key", serialized.lower())
            self.assertNotIn("authorization", serialized.lower())

    def test_never_overwrites_existing_snapshot(self):
        collected = datetime(2026, 9, 24, 18, 30, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as tmp:
            collect_live_tennis_snapshot(
                _FakeClient(),
                output_dir=tmp,
                collected_at=collected,
            )

            with self.assertRaises(FileExistsError):
                collect_live_tennis_snapshot(
                    _FakeClient(),
                    output_dir=tmp,
                    collected_at=collected,
                )

            files = list(Path(tmp).glob("*.json"))
            self.assertEqual(len(files), 1)

    def test_rejects_naive_collection_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "timezone"):
                collect_live_tennis_snapshot(
                    _FakeClient(),
                    output_dir=tmp,
                    collected_at=datetime(2026, 9, 24, 18, 30),
                )


if __name__ == "__main__":
    unittest.main()
