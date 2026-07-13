from __future__ import annotations

import unittest

from zcounter.providers.codex.usage_api import (
    UsageShapeError,
    build_codex_display_slots,
    normalize_codex_usage,
    normalize_usage_response,
    window_label_from_seconds,
)


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
        self.assertEqual(five_hour.window_seconds, 18_000)
        self.assertIsNone(weekly)

    def test_null_or_missing_window_remains_unavailable(self) -> None:
        five_hour, weekly = normalize_usage_response(
            _response(None, {"used_percent": 25, "reset_at": None, "limit_window_seconds": 604_800})
        )

        self.assertIsNone(five_hour)
        self.assertEqual(weekly.used_percent, 25)
        self.assertEqual(weekly.window_seconds, 604_800)
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
            _response(
                {"used_percent": -1},
                {"used_percent": 40, "reset_at": 1_800_000_000, "limit_window_seconds": 604_800},
            )
        )

        self.assertIsNone(five_hour)
        self.assertEqual(weekly.used_percent, 40)
        self.assertEqual(weekly.window_seconds, 604_800)

    def test_non_numeric_or_non_finite_primary_does_not_discard_valid_secondary(self) -> None:
        invalid_values = (-1, 101, float("nan"), float("inf"), float("-inf"), True, "1", None)
        for value in invalid_values:
            with self.subTest(value=repr(value)):
                five_hour, weekly = normalize_usage_response(
                    _response(
                        {"used_percent": value},
                        {"used_percent": 40, "limit_window_seconds": 604_800},
                    )
                )
                self.assertIsNone(five_hour)
                self.assertEqual(weekly.used_percent, 40)

    def test_current_api_shape_week_only_in_primary(self) -> None:
        usage = normalize_codex_usage(
            _response(
                {"used_percent": 0, "reset_at": 1_800_000_000, "limit_window_seconds": 604_800},
                None,
            )
        )

        self.assertIsNone(usage.five_hour)
        self.assertIsNotNone(usage.weekly)
        assert usage.weekly is not None
        self.assertEqual(usage.weekly.window_seconds, 604_800)
        self.assertEqual(usage.primary_label, "WEEK")
        self.assertIsNone(usage.secondary)
        self.assertIsNone(usage.secondary_label)

    def test_legacy_shape_five_hour_and_week(self) -> None:
        usage = normalize_codex_usage(
            _response(
                {"used_percent": 10, "reset_at": 1_800_000_000, "limit_window_seconds": 18_000},
                {"used_percent": 20, "reset_at": 1_800_000_000, "limit_window_seconds": 604_800},
            )
        )

        self.assertEqual(usage.five_hour.used_percent, 10)
        self.assertEqual(usage.weekly.used_percent, 20)
        self.assertEqual(usage.primary_label, "5H")
        self.assertEqual(usage.secondary_label, "WEEK")

    def test_five_hour_only(self) -> None:
        usage = normalize_codex_usage(
            _response({"used_percent": 15, "reset_at": 1_800_000_000, "limit_window_seconds": 18_000})
        )

        self.assertIsNotNone(usage.five_hour)
        self.assertIsNone(usage.weekly)
        self.assertEqual(usage.primary_label, "5H")
        self.assertIsNone(usage.secondary)

    def test_reversed_api_slots_still_show_five_hour_then_week(self) -> None:
        usage = normalize_codex_usage(
            _response(
                {"used_percent": 30, "reset_at": 1_800_000_000, "limit_window_seconds": 604_800},
                {"used_percent": 5, "reset_at": 1_800_000_000, "limit_window_seconds": 18_000},
            )
        )

        self.assertEqual(usage.five_hour.used_percent, 5)
        self.assertEqual(usage.weekly.used_percent, 30)
        self.assertEqual(usage.primary_label, "5H")
        self.assertEqual(usage.secondary_label, "WEEK")

    def test_unknown_window_duration_uses_day_label(self) -> None:
        usage = normalize_codex_usage(
            _response({"used_percent": 12, "reset_at": 1_800_000_000, "limit_window_seconds": 86_400})
        )

        self.assertIsNone(usage.five_hour)
        self.assertIsNone(usage.weekly)
        self.assertEqual(usage.primary_label, "1D")

    def test_both_windows_null_raises(self) -> None:
        with self.assertRaises(UsageShapeError):
            normalize_codex_usage(_response(None, None))

    def test_window_label_from_seconds(self) -> None:
        self.assertEqual(window_label_from_seconds(18_000), "5H")
        self.assertEqual(window_label_from_seconds(604_800), "WEEK")
        self.assertEqual(window_label_from_seconds(86_400), "1D")
        self.assertEqual(window_label_from_seconds(172_800), "2D")
        self.assertEqual(window_label_from_seconds(3_600), "1H")
        self.assertEqual(window_label_from_seconds(21_600), "6H")
        self.assertEqual(window_label_from_seconds(90_001), "WINDOW")

    def test_build_codex_display_slots_sorts_by_duration(self) -> None:
        from zcounter.models import RateWindow

        week = RateWindow(30, 70, None, 10_080, 604_800)
        five_hour = RateWindow(5, 95, None, 300, 18_000)
        primary, secondary, primary_label, secondary_label = build_codex_display_slots(
            [week, five_hour]
        )

        self.assertEqual(primary.window_seconds, 18_000)
        self.assertEqual(secondary.window_seconds, 604_800)
        self.assertEqual(primary_label, "5H")
        self.assertEqual(secondary_label, "WEEK")


if __name__ == "__main__":
    unittest.main()
