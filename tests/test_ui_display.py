from __future__ import annotations

import unittest
from datetime import datetime, timezone

from zcounter.models import QuotaSnapshot, RateWindow
from zcounter.ui.display import (
    format_account_row,
    format_cursor_row,
    format_daily_pace,
    format_status_suffix,
    format_updated_at_jst,
    format_updated_footer,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_STALE,
)


class UIDisplayTests(unittest.TestCase):
    def test_format_updated_at_jst_from_utc(self) -> None:
        updated = datetime(2026, 5, 29, 7, 4, 40, 925803, tzinfo=timezone.utc)
        self.assertEqual(format_updated_at_jst(updated), "2026/5/29(金) 16:04:40 JST")

    def test_format_updated_footer(self) -> None:
        updated = datetime(2026, 5, 29, 7, 4, 40, tzinfo=timezone.utc)
        self.assertEqual(
            format_updated_footer(updated),
            "updated 2026/5/29(金) 16:04:40 JST : refresh 300s",
        )

    def test_format_daily_pace(self) -> None:
        reset_at = datetime(2026, 6, 28, 0, 36, tzinfo=timezone.utc)
        now = datetime(2026, 6, 13, 0, 36, tzinfo=timezone.utc)
        window = RateWindow(38.0, 62.0, reset_at, None)
        self.assertEqual(format_daily_pace(window, now), "4.1%/d")

    def test_format_daily_pace_returns_now_after_reset(self) -> None:
        reset_at = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
        now = datetime(2026, 6, 2, 0, 0, tzinfo=timezone.utc)
        window = RateWindow(0.0, 0.0, reset_at, None)
        self.assertEqual(format_daily_pace(window, now), "now")

    def test_format_cursor_row(self) -> None:
        reset_at = datetime(2026, 6, 28, 0, 36, tzinfo=timezone.utc).astimezone()
        snapshot = QuotaSnapshot(
            provider="cursor",
            email="rock@zurg.jp",
            plan="Cursor Pro",
            chatgpt_account_id=None,
            five_hour=None,
            weekly=None,
            source="cursor-usage-summary",
            updated_at=datetime(2026, 5, 29, 7, 4, 40, tzinfo=timezone.utc),
            primary=RateWindow(1.0, 99.0, reset_at, None),
            secondary=RateWindow(1.0, 99.0, reset_at, None),
            tertiary=RateWindow(0.0, 100.0, reset_at, None),
            primary_label="Total",
            secondary_label="Auto(+Composer)",
            tertiary_label="API",
        )
        row = format_cursor_row(snapshot)
        self.assertIn("rock@zurg.jp", row)
        self.assertIn("Total 99%", row)
        self.assertIn("Auto(+Composer) 99%", row)
        self.assertIn("API 100%", row)
        self.assertIn("2026/6/28", row)

    def test_format_account_row_uses_codex_layout(self) -> None:
        reset_at = datetime(2026, 5, 31, 0, 54, tzinfo=timezone.utc).astimezone()
        snapshot = QuotaSnapshot(
            provider="codex",
            email="rock@zurg.jp",
            plan="plus",
            chatgpt_account_id="id",
            five_hour=RateWindow(46.0, 54.0, datetime.now(tz=timezone.utc), 300),
            weekly=RateWindow(7.0, 93.0, reset_at, 10080),
            source="wham-usage",
            updated_at=datetime(2026, 5, 29, 7, 4, 40, tzinfo=timezone.utc),
            primary_label="5H",
            secondary_label="WEEK",
        )
        row = format_account_row(snapshot)
        self.assertIn("5H", row)
        self.assertIn("WEEK", row)
        self.assertNotIn("Total", row)

    def test_cursor_status_suffix_hides_error(self) -> None:
        snapshot = QuotaSnapshot(
            provider="cursor",
            email=None,
            plan=None,
            chatgpt_account_id=None,
            five_hour=None,
            weekly=None,
            source="cursor-usage-summary",
            updated_at=datetime(2026, 5, 29, 7, 4, 40, tzinfo=timezone.utc),
            error="cursor session is invalid or expired",
        )
        self.assertEqual(format_status_suffix(STATUS_ERROR, snapshot), "")
        self.assertEqual(format_status_suffix(STATUS_STALE, snapshot), "stale")
        self.assertEqual(format_status_suffix(STATUS_OK, snapshot), "")


if __name__ == "__main__":
    unittest.main()
