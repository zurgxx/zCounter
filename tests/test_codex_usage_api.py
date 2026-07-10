from __future__ import annotations

import unittest

from zcounter.providers.codex.usage_api import UsageShapeError, normalize_usage_response


def _response(primary, secondary=None):
    return {
        "rate_limit": {
            "primary_window": primary,
            "secondary_window": secondary,
        }
    }


class CodexUsageAPITests(unittest.TestCase):
    def test_zero_usage_is_a_valid_initial_window(self) -> None:
        five_hour, weekly = normalize_usage_response(
            _response({"used_percent": 0, "reset_at": 1_800_000_000, "limit_window_seconds": 18_000})
        )

        self.assertEqual(five_hour.used_percent, 0)
        self.assertEqual(five_hour.remaining_percent, 100)
        self.assertIsNone(weekly)

    def test_null_or_missing_window_remains_unavailable(self) -> None:
        five_hour, weekly = normalize_usage_response(
            _response(None, {"used_percent": 25, "reset_at": None, "limit_window_seconds": 604_800})
        )

        self.assertIsNone(five_hour)
        self.assertEqual(weekly.used_percent, 25)
        self.assertIsNone(weekly.reset_at)

        five_hour, weekly = normalize_usage_response(
            _response({}, {"used_percent": 25, "reset_at": None, "limit_window_seconds": 604_800})
        )
        self.assertIsNone(five_hour)
        self.assertEqual(weekly.used_percent, 25)

    def test_out_of_range_window_is_not_clamped_to_a_fake_full_or_empty_quota(self) -> None:
        with self.assertRaises(UsageShapeError):
            normalize_usage_response(_response({"used_percent": -1}, {"used_percent": 101}))

    def test_invalid_primary_does_not_discard_valid_secondary(self) -> None:
        five_hour, weekly = normalize_usage_response(
            _response({"used_percent": -1}, {"used_percent": 40, "reset_at": 1_800_000_000})
        )

        self.assertIsNone(five_hour)
        self.assertEqual(weekly.used_percent, 40)

    def test_non_numeric_or_non_finite_primary_does_not_discard_valid_secondary(self) -> None:
        invalid_values = (-1, 101, float("nan"), float("inf"), float("-inf"), True, "1", None)
        for value in invalid_values:
            with self.subTest(value=repr(value)):
                five_hour, weekly = normalize_usage_response(
                    _response({"used_percent": value}, {"used_percent": 40})
                )
                self.assertIsNone(five_hour)
                self.assertEqual(weekly.used_percent, 40)


if __name__ == "__main__":
    unittest.main()
