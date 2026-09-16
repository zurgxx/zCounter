from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from zcounter.models import QuotaSnapshot, RateWindow
from zcounter.notify.cursor_api import (
    cursor_api_remaining_percent,
    format_api_decrease_message,
    maybe_notify_cursor_api_decrease,
    should_notify_api_decrease,
)


def _cursor_snapshot(api_remaining: float | None = 69.0, *, error: str | None = None) -> QuotaSnapshot:
    total = RateWindow(46.0, 54.0, None, None)
    first_party = RateWindow(63.0, 37.0, None, None)
    tertiary = (
        RateWindow(100.0 - api_remaining, api_remaining, None, None)
        if api_remaining is not None
        else None
    )
    return QuotaSnapshot(
        provider="cursor",
        email="cursor@example.com",
        plan="Cursor Pro",
        chatgpt_account_id=None,
        five_hour=None,
        weekly=None,
        primary=total,
        secondary=first_party,
        tertiary=tertiary,
        primary_label="Total",
        secondary_label="First-party models",
        tertiary_label="API" if tertiary is not None else None,
        source="cursor-usage-summary",
        updated_at=datetime(2026, 9, 16, 1, 12, tzinfo=timezone.utc),
        provider_account_id="cursor-id",
        error=error,
    )


class CursorApiNotifyTests(unittest.TestCase):
    def test_should_notify_for_one_percent_decrease(self) -> None:
        self.assertTrue(should_notify_api_decrease(100.0, 99.0))

    def test_should_notify_for_two_percent_decrease(self) -> None:
        self.assertTrue(should_notify_api_decrease(99.0, 97.0))

    def test_should_not_notify_when_unchanged(self) -> None:
        self.assertFalse(should_notify_api_decrease(99.0, 99.0))

    def test_should_not_notify_when_increased(self) -> None:
        self.assertFalse(should_notify_api_decrease(97.0, 100.0))

    def test_should_not_notify_on_first_value(self) -> None:
        self.assertFalse(should_notify_api_decrease(None, 100.0))

    def test_format_message_includes_jst_timestamp(self) -> None:
        recorded_at = datetime(2026, 9, 16, 1, 12, tzinfo=timezone.utc)
        message = format_api_decrease_message(69.0, 68.0, recorded_at)

        self.assertIn("⚠️ zCounter API usage decreased", message)
        self.assertIn("Cursor API remaining: 69% → 68% (-1%)", message)
        self.assertIn("2026-09-16 10:12 JST", message)

    def test_cursor_api_remaining_percent_reads_tertiary(self) -> None:
        self.assertEqual(cursor_api_remaining_percent(_cursor_snapshot(68.4)), 68.4)

    def test_maybe_notify_skips_first_refresh(self) -> None:
        recorded_at = datetime(2026, 9, 16, 1, 12, tzinfo=timezone.utc)
        with mock.patch("zcounter.notify.cursor_api.send_discord_message") as send:
            new_previous = maybe_notify_cursor_api_decrease(
                None,
                [_cursor_snapshot(100.0)],
                recorded_at,
                webhook_url="https://example.invalid/webhook",
            )

        self.assertEqual(new_previous, 100.0)
        send.assert_not_called()

    def test_maybe_notify_sends_on_decrease(self) -> None:
        recorded_at = datetime(2026, 9, 16, 1, 12, tzinfo=timezone.utc)
        with mock.patch("zcounter.notify.cursor_api.send_discord_message", return_value=True) as send:
            new_previous = maybe_notify_cursor_api_decrease(
                100.0,
                [_cursor_snapshot(99.0)],
                recorded_at,
                webhook_url="https://example.invalid/webhook",
            )

        self.assertEqual(new_previous, 99.0)
        send.assert_called_once()
        message = send.call_args.args[0]
        self.assertIn("100% → 99%", message)

    def test_maybe_notify_does_not_send_when_unchanged(self) -> None:
        with mock.patch("zcounter.notify.cursor_api.send_discord_message") as send:
            new_previous = maybe_notify_cursor_api_decrease(
                99.0,
                [_cursor_snapshot(99.0)],
                datetime.now(timezone.utc),
            )

        self.assertEqual(new_previous, 99.0)
        send.assert_not_called()

    def test_maybe_notify_does_not_send_when_increased(self) -> None:
        with mock.patch("zcounter.notify.cursor_api.send_discord_message") as send:
            new_previous = maybe_notify_cursor_api_decrease(
                97.0,
                [_cursor_snapshot(100.0)],
                datetime.now(timezone.utc),
            )

        self.assertEqual(new_previous, 100.0)
        send.assert_not_called()

    def test_maybe_notify_continues_when_send_fails(self) -> None:
        with mock.patch(
            "zcounter.notify.cursor_api.send_discord_message",
            side_effect=RuntimeError("boom"),
        ):
            with mock.patch("zcounter.notify.cursor_api.logger.warning") as warning:
                new_previous = maybe_notify_cursor_api_decrease(
                    100.0,
                    [_cursor_snapshot(98.0)],
                    datetime.now(timezone.utc),
                )

        self.assertEqual(new_previous, 98.0)
        warning.assert_called_once()

    def test_maybe_notify_keeps_previous_when_cursor_api_missing(self) -> None:
        snapshot = _cursor_snapshot(None)
        with mock.patch("zcounter.notify.cursor_api.send_discord_message") as send:
            new_previous = maybe_notify_cursor_api_decrease(
                80.0,
                [snapshot],
                datetime.now(timezone.utc),
            )

        self.assertEqual(new_previous, 80.0)
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
