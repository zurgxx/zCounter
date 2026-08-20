from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from zcounter.models import QuotaSnapshot, RateWindow
from zcounter.ui.usage_log import append_usage_log, format_usage_log_line, usage_log_path


def _codex_snapshot(
    email: str,
    five_hour: float | None = 72.0,
    weekly: float | None = 41.0,
    *,
    error: str | None = None,
) -> QuotaSnapshot:
    five_hour_window = (
        RateWindow(28.0, five_hour, None, 300, 18_000)
        if five_hour is not None
        else None
    )
    weekly_window = (
        RateWindow(59.0, weekly, None, 10_080, 604_800)
        if weekly is not None
        else None
    )
    return QuotaSnapshot(
        provider="codex",
        email=email,
        plan="plus",
        chatgpt_account_id=email,
        five_hour=five_hour_window,
        weekly=weekly_window,
        primary=five_hour_window,
        secondary=weekly_window,
        primary_label="5H",
        secondary_label="WEEK",
        provider_account_id=email,
        source="wham-usage",
        updated_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        error=error,
    )


def _cursor_snapshot(email: str = "cursor@example.com") -> QuotaSnapshot:
    total = RateWindow(46.0, 54.0, None, None)
    first_party = RateWindow(63.0, 37.0, None, None)
    return QuotaSnapshot(
        provider="cursor",
        email=email,
        plan="Cursor Pro",
        chatgpt_account_id=None,
        five_hour=None,
        weekly=None,
        primary=total,
        secondary=first_party,
        tertiary=None,
        primary_label="Total",
        secondary_label="First-party models",
        source="cursor-usage-summary",
        updated_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        provider_account_id="cursor-id",
    )


class UsageLogTests(unittest.TestCase):
    def test_format_uses_existing_account_labels_and_available_quota_slots(self) -> None:
        recorded_at = datetime(2026, 8, 20, 14, 5, 12, tzinfo=timezone.utc)

        line = format_usage_log_line(
            [
                _codex_snapshot("codex-main@example.com"),
                _codex_snapshot("codex-sub@example.com", five_hour=88.0, weekly=63.0),
                _cursor_snapshot(),
            ],
            recorded_at,
        )

        self.assertIsNotNone(line)
        self.assertIn(
            f"{recorded_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')} ",
            line,
        )
        self.assertIn("codex-main:five_hour=72%,weekly=41%", line)
        self.assertIn("codex-sub:five_hour=88%,weekly=63%", line)
        self.assertIn("cursor:total=54%,first_party_models=37%", line)
        self.assertEqual(line.count("\n"), 1)

    def test_missing_quota_is_omitted_and_accounts_are_dynamic(self) -> None:
        snapshot = _codex_snapshot("codex-main@example.com", five_hour=None, weekly=41.0)

        line = format_usage_log_line([snapshot], datetime.now(timezone.utc))

        self.assertIsNotNone(line)
        self.assertIn("codex-main:weekly=41%", line)
        self.assertNotIn("five_hour", line)

    def test_error_snapshot_does_not_produce_partial_or_stale_log_line(self) -> None:
        line = format_usage_log_line(
            [_codex_snapshot("codex-main@example.com"), _codex_snapshot("codex-sub@example.com", error="failed")],
            datetime.now(timezone.utc),
        )

        self.assertIsNone(line)

    def test_append_preserves_existing_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.log"
            path.write_text("old line\n", encoding="utf-8")

            appended = append_usage_log(
                [_codex_snapshot("codex-main@example.com")],
                datetime(2026, 8, 20, 14, 5, 12, tzinfo=timezone.utc),
                path,
            )

            self.assertTrue(appended)
            self.assertEqual(path.read_text(encoding="utf-8").splitlines(), [
                "old line",
                mock.ANY,
            ])

    def test_path_uses_xdg_state_home_and_explicit_override(self) -> None:
        with mock.patch.dict("os.environ", {"XDG_STATE_HOME": "/tmp/zcounter-state"}, clear=True):
            self.assertEqual(
                usage_log_path(),
                Path("/tmp/zcounter-state/zcounter/usage.log"),
            )
        with mock.patch.dict("os.environ", {"ZCOUNTER_USAGE_LOG": "~/usage.log"}, clear=True):
            self.assertEqual(usage_log_path(), Path.home() / "usage.log")


if __name__ == "__main__":
    unittest.main()
