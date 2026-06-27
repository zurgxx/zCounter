from __future__ import annotations

import unittest
from datetime import datetime, timezone

from zcounter.providers.codex.usage_api import normalize_reset_credits_response


class CodexResetCreditsTests(unittest.TestCase):
    def test_decodes_available_credits_and_sorts_expires(self) -> None:
        now = datetime(2026, 6, 27, tzinfo=timezone.utc)
        payload = {
            "available_count": 2,
            "credits": [
                {
                    "id": "later",
                    "status": "available",
                    "expires_at": "2026-07-27T00:39:53.731630Z",
                },
                {
                    "id": "earlier",
                    "status": "available",
                    "expires_at": "2026-07-12T04:03:43.263391Z",
                },
                {
                    "id": "expired",
                    "status": "available",
                    "expires_at": "2026-06-01T00:00:00Z",
                },
                {
                    "id": "redeemed",
                    "status": "redeemed",
                    "expires_at": "2026-08-01T00:00:00Z",
                },
            ],
        }

        credits = normalize_reset_credits_response(payload, now=now)

        self.assertIsNotNone(credits)
        assert credits is not None
        self.assertEqual(credits.available_count, 2)
        self.assertEqual(len(credits.expires_at), 2)
        self.assertEqual(credits.expires_at[0].day, 12)
        self.assertEqual(credits.expires_at[1].day, 27)

    def test_rejects_negative_available_count(self) -> None:
        payload = {"available_count": -1, "credits": []}
        self.assertIsNone(normalize_reset_credits_response(payload))

    def test_zero_available_count_returns_empty_expires(self) -> None:
        payload = {"available_count": 0, "credits": []}
        credits = normalize_reset_credits_response(payload)
        self.assertIsNotNone(credits)
        assert credits is not None
        self.assertEqual(credits.available_count, 0)
        self.assertEqual(credits.expires_at, ())


if __name__ == "__main__":
    unittest.main()
