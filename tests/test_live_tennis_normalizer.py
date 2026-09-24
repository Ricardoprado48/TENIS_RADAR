"""Testes do contrato Live Tennis -> Fase 8.

São determinísticos e não fazem chamadas HTTP.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from src.radar.live_tennis_normalizer import (
    LiveTennisNormalizationError,
    normalize_upcoming_to_phase8,
)


def _match(**overrides):
    row = {
        "id": 195443,
        "status": "upcoming",
        "tour": "atp",
        "tournament": "Hangzhou",
        "surface": "hard",
        "round": "ATP Hangzhou - 1/8-finals",
        "round_code": "R16",
        "scheduled_time": "2026-09-25T00:30:00Z",
        "tournament_id": "11724",
        "players": {
            "p1": {"id": 115, "name": "Jaime Faria"},
            "p2": {"id": 233, "name": "Hugo Gaston"},
        },
    }
    row.update(overrides)
    return row


def _fixture(**overrides):
    row = {
        "id": 36555,
        "match_id": 195443,
        "event_date": "2026-09-24",
        "tour": "atp",
        "tournament": "Hangzhou",
        "surface": "hard",
        "round_code": "R16",
        "status": "upcoming",
    }
    row.update(overrides)
    return row


class TestLiveTennisPhase8Normalizer(unittest.TestCase):
    def test_maps_to_required_phase8_contract_and_uses_fixture_event_date(self):
        collected_at = datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc)

        df = normalize_upcoming_to_phase8(
            "ATP",
            [_match()],
            [_fixture()],
            collected_at=collected_at,
        )

        self.assertEqual(len(df), 1)
        row = df.iloc[0]
        self.assertEqual(row["tour"], "ATP")
        self.assertEqual(row["tournament"], "Hangzhou")
        self.assertEqual(row["surface"], "hard")
        # Prova a decisão crítica: a data vem do fixture, não do dia UTC
        # contido em scheduled_time.
        self.assertEqual(row["match_date"], "2026-09-24")
        self.assertEqual(row["round"], "R16")
        self.assertEqual(row["player_a_raw"], "Jaime Faria")
        self.assertEqual(row["player_b_raw"], "Hugo Gaston")
        self.assertEqual(row["live_tennis_match_id"], 195443)
        self.assertEqual(row["live_tennis_fixture_id"], 36555)
        self.assertEqual(row["collected_at"], "2026-09-24T18:00:00Z")
        self.assertIn("status=upcoming", row["source_url"])

    def test_round_falls_back_to_unknown_without_guessing_free_text(self):
        df = normalize_upcoming_to_phase8(
            "ATP",
            [_match(round_code=None)],
            [_fixture(round_code=None)],
            collected_at=datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(df.iloc[0]["round"], "UNKNOWN")

    def test_missing_fixture_blocks_normalization_instead_of_guessing_match_date(self):
        with self.assertRaisesRegex(
            LiveTennisNormalizationError,
            "fixture correspondente não encontrado",
        ):
            normalize_upcoming_to_phase8(
                "ATP",
                [_match()],
                [],
                collected_at=datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc),
            )

    def test_duplicate_fixture_match_id_is_rejected_as_ambiguous(self):
        with self.assertRaisesRegex(
            LiveTennisNormalizationError,
            "mais de um fixture",
        ):
            normalize_upcoming_to_phase8(
                "ATP",
                [_match()],
                [_fixture(id=1), _fixture(id=2)],
                collected_at=datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc),
            )

    def test_missing_player_name_is_rejected(self):
        bad = _match(
            players={
                "p1": {"id": 115, "name": ""},
                "p2": {"id": 233, "name": "Hugo Gaston"},
            }
        )
        with self.assertRaisesRegex(
            LiveTennisNormalizationError,
            "players.p1.name",
        ):
            normalize_upcoming_to_phase8(
                "ATP",
                [bad],
                [_fixture()],
                collected_at=datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
