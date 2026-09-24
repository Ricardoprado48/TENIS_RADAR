"""Testes unitários do cliente Live Tennis.

Não fazem chamadas reais nem consomem quota da API.
"""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from src.radar.live_tennis import LiveTennisAPIError, LiveTennisClient


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class TestLiveTennisClient(unittest.TestCase):
    def test_missing_api_key_fails_before_http_request(self):
        with self.assertRaises(LiveTennisAPIError):
            LiveTennisClient(api_key="   ")

    def test_fetches_upcoming_atp_singles_with_expected_filters(self):
        session = Mock()
        session.get.return_value = _FakeResponse(
            {
                "data": [
                    {
                        "id": 195443,
                        "status": "upcoming",
                        "tour": "atp",
                        "draw": "singles",
                        "scheduled_time": "2026-09-25T11:30:00Z",
                    }
                ],
                "meta": {"has_more": False, "count": 1, "limit": 50, "offset": 0},
            }
        )

        client = LiveTennisClient(api_key="test-key", session=session)
        rows = client.list_upcoming_singles("ATP")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 195443)

        _args, kwargs = session.get.call_args
        self.assertEqual(
            kwargs["params"],
            {
                "status": "upcoming",
                "tour": "atp",
                "draw": "singles",
                "limit": 50,
                "offset": 0,
            },
        )
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")

    def test_paginates_using_returned_row_count(self):
        session = Mock()
        session.get.side_effect = [
            _FakeResponse(
                {
                    "data": [
                        {"id": 1, "status": "upcoming"},
                        {"id": 2, "status": "upcoming"},
                    ],
                    "meta": {"has_more": True},
                }
            ),
            _FakeResponse(
                {
                    "data": [{"id": 3, "status": "upcoming"}],
                    "meta": {"has_more": False},
                }
            ),
        ]

        client = LiveTennisClient(api_key="test-key", session=session)
        rows = client.list_upcoming_singles("WTA", page_size=2)

        self.assertEqual([row["id"] for row in rows], [1, 2, 3])
        self.assertEqual(session.get.call_count, 2)
        second_call = session.get.call_args_list[1]
        self.assertEqual(second_call.kwargs["params"]["offset"], 2)

    def test_rejects_non_upcoming_row_from_upcoming_endpoint(self):
        session = Mock()
        session.get.return_value = _FakeResponse(
            {
                "data": [{"id": 99, "status": "finished"}],
                "meta": {"has_more": False},
            }
        )

        client = LiveTennisClient(api_key="test-key", session=session)
        with self.assertRaises(LiveTennisAPIError):
            client.list_upcoming_singles("ATP")

    def test_rejects_invalid_tour_without_http_request(self):
        session = Mock()
        client = LiveTennisClient(api_key="test-key", session=session)

        with self.assertRaises(ValueError):
            client.list_upcoming_singles("CHALLENGER")

        session.get.assert_not_called()

    def test_http_error_does_not_expose_api_key(self):
        session = Mock()
        session.get.return_value = _FakeResponse({"error": "unauthorized"}, status_code=401)

        client = LiveTennisClient(api_key="SECRET_KEY", session=session)

        with self.assertRaises(LiveTennisAPIError) as ctx:
            client.list_upcoming_singles("ATP")

        self.assertNotIn("SECRET_KEY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
