from __future__ import annotations

import unittest
from datetime import datetime, timezone

from zcounter.models import CodexResetCredits, QuotaSnapshot, RateWindow
from zcounter.ui.display import STATUS_OK, STATUS_STALE
from zcounter.ui.viewmodel import SnapshotStore, build_payload


def _cursor_snapshot(
    *,
    total_remaining: float = 62.0,
    auto_remaining: float = 45.0,
    api_remaining: float = 99.0,
    reset_at: datetime | None = None,
) -> QuotaSnapshot:
    reset = reset_at or datetime(2026, 6, 28, 0, 36, tzinfo=timezone.utc)
    return QuotaSnapshot(
        provider="cursor",
        email="rock@example.com",
        plan="Cursor Pro",
        chatgpt_account_id=None,
        five_hour=None,
        weekly=None,
        source="cursor-usage-summary",
        updated_at=datetime(2026, 6, 13, 0, 36, tzinfo=timezone.utc),
        primary=RateWindow(100.0 - total_remaining, total_remaining, reset, None),
        secondary=RateWindow(100.0 - auto_remaining, auto_remaining, reset, None),
        tertiary=RateWindow(100.0 - api_remaining, api_remaining, reset, None),
        primary_label="Total",
        secondary_label="Auto(+Composer)",
        tertiary_label="API",
    )


def _snapshot(
    *,
    remaining: float = 50.0,
    error: str | None = None,
    email: str | None = "rock@example.com",
) -> QuotaSnapshot:
    window = None if error else RateWindow(100.0 - remaining, remaining, None, 300)
    return QuotaSnapshot(
        provider="codex",
        email=email,
        plan="plus",
        chatgpt_account_id="account-id" if not error else None,
        five_hour=window,
        weekly=window,
        source="wham-usage",
        updated_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
        error=error,
        primary=window,
        secondary=window,
        primary_label="5H usage",
        secondary_label="Weekly",
        provider_account_id="account-id" if not error else None,
    )


class UIViewModelTests(unittest.TestCase):
    def test_payload_uses_local_part_and_critical_level(self) -> None:
        payload = build_payload(
            [(_snapshot(remaining=9.4), STATUS_OK)],
            datetime(2026, 5, 31, tzinfo=timezone.utc),
        )

        self.assertEqual(payload["critical_count"], 1)
        self.assertEqual(payload["accounts"][0]["account"], "rock")
        self.assertEqual(payload["accounts"][0]["status_label"], "Critical")
        self.assertEqual(payload["accounts"][0]["metrics"][0]["remaining_percent"], 9)

    def test_warning_starts_below_forty_percent(self) -> None:
        payload = build_payload(
            [(_snapshot(remaining=39.9), STATUS_OK)],
            datetime(2026, 5, 31, tzinfo=timezone.utc),
        )

        self.assertEqual(payload["warning_count"], 1)
        self.assertEqual(payload["accounts"][0]["status_label"], "Warning")

    def test_critical_starts_below_twenty_percent(self) -> None:
        payload = build_payload(
            [(_snapshot(remaining=19.9), STATUS_OK)],
            datetime(2026, 5, 31, tzinfo=timezone.utc),
        )

        self.assertEqual(payload["critical_count"], 1)
        self.assertEqual(payload["accounts"][0]["status_label"], "Critical")

    def test_store_reuses_single_provider_cache_for_error_without_account_id(self) -> None:
        store = SnapshotStore()
        store.merge([_snapshot(remaining=54)])

        rows = store.merge([_snapshot(error="request failed", email=None)])

        snapshot, status = rows[0]
        self.assertEqual(status, STATUS_STALE)
        self.assertEqual(snapshot.email, "rock@example.com")
        self.assertEqual(snapshot.primary.remaining_percent, 54)

    def test_cursor_hero_layout_footer_and_sub_metrics(self) -> None:
        payload = build_payload(
            [(_cursor_snapshot(), STATUS_OK)],
            datetime(2026, 6, 13, 0, 36, tzinfo=timezone.utc),
        )
        account = payload["accounts"][0]
        self.assertEqual(account["display_mode"], "cursor-hero")
        cursor = account["cursor"]
        self.assertEqual(cursor["total"]["label"], "Total")
        self.assertEqual(cursor["total"]["remaining_percent"], 62)
        self.assertNotIn("pace", cursor["total"])
        self.assertEqual(len(cursor["sub_metrics"]), 2)
        self.assertEqual(cursor["sub_metrics"][0]["label"], "Auto(+Composer)")
        self.assertEqual(cursor["sub_metrics"][0]["remaining_percent"], 45)
        self.assertEqual(cursor["sub_metrics"][1]["label"], "API")
        self.assertEqual(cursor["sub_metrics"][1]["remaining_percent"], 99)
        self.assertEqual(cursor["footer"]["reset"], "6/28(日) 9:36")
        self.assertEqual(cursor["footer"]["pace"], "4.1%/d")
        self.assertEqual(cursor["footer"]["pace_level"], "safe")

    def test_cursor_uses_pace_for_warning_and_critical(self) -> None:
        reset_at = datetime(2026, 6, 28, 0, 36, tzinfo=timezone.utc)
        now = datetime(2026, 6, 13, 0, 36, tzinfo=timezone.utc)
        warning_payload = build_payload(
            [(_cursor_snapshot(total_remaining=42.0, auto_remaining=25.0, reset_at=reset_at), STATUS_OK)],
            now,
        )
        warning_account = warning_payload["accounts"][0]
        self.assertEqual(warning_account["level"], "warning")
        self.assertEqual(warning_account["status_label"], "Warning")
        self.assertEqual(warning_payload["warning_count"], 1)
        self.assertEqual(warning_account["cursor"]["total"]["level"], "safe")
        self.assertEqual(warning_account["cursor"]["sub_metrics"][0]["level"], "safe")
        self.assertEqual(warning_account["cursor"]["footer"]["pace_level"], "warning")

        critical_payload = build_payload(
            [(_cursor_snapshot(total_remaining=10.0, auto_remaining=8.0, reset_at=reset_at), STATUS_OK)],
            now,
        )
        critical_account = critical_payload["accounts"][0]
        self.assertEqual(critical_account["level"], "critical")
        self.assertEqual(critical_account["status_label"], "Critical")
        self.assertEqual(critical_payload["critical_count"], 1)
        self.assertEqual(critical_account["cursor"]["total"]["level"], "safe")
        self.assertEqual(critical_account["cursor"]["sub_metrics"][0]["level"], "safe")
        self.assertEqual(critical_account["cursor"]["footer"]["pace_level"], "critical")

    def test_cursor_metrics_stay_safe_when_only_auto_pace_would_warn(self) -> None:
        reset_at = datetime(2026, 6, 28, 0, 36, tzinfo=timezone.utc)
        now = datetime(2026, 6, 13, 0, 36, tzinfo=timezone.utc)
        payload = build_payload(
            [(_cursor_snapshot(total_remaining=62.0, auto_remaining=39.0, reset_at=reset_at), STATUS_OK)],
            now,
        )
        account = payload["accounts"][0]
        self.assertEqual(account["level"], "safe")
        self.assertEqual(account["cursor"]["total"]["level"], "safe")
        self.assertEqual(account["cursor"]["sub_metrics"][0]["level"], "safe")
        self.assertEqual(account["cursor"]["footer"]["pace_level"], "safe")
        self.assertEqual(account["cursor"]["footer"]["pace"], "4.1%/d")

    def test_codex_metrics_keep_reset_on_both(self) -> None:
        payload = build_payload(
            [(_snapshot(remaining=54), STATUS_OK)],
            datetime(2026, 5, 31, tzinfo=timezone.utc),
        )
        metrics = payload["accounts"][0]["metrics"]
        self.assertNotIn("pace", metrics[0])
        self.assertNotIn("pace", metrics[1])

    def test_codex_reset_credits_payload_uses_sub_foot_fields(self) -> None:
        snapshot = _snapshot(remaining=54)
        snapshot = QuotaSnapshot(
            provider=snapshot.provider,
            email=snapshot.email,
            plan=snapshot.plan,
            chatgpt_account_id=snapshot.chatgpt_account_id,
            five_hour=snapshot.five_hour,
            weekly=snapshot.weekly,
            source=snapshot.source,
            updated_at=snapshot.updated_at,
            error=snapshot.error,
            primary=snapshot.primary,
            secondary=snapshot.secondary,
            primary_label=snapshot.primary_label,
            secondary_label=snapshot.secondary_label,
            provider_account_id=snapshot.provider_account_id,
            codex_reset_credits=CodexResetCredits(
                available_count=2,
                expires_at=(
                    datetime(2026, 7, 12, 4, 3, 43, tzinfo=timezone.utc),
                    datetime(2026, 7, 27, 0, 39, 53, tzinfo=timezone.utc),
                ),
            ),
        )
        payload = build_payload(
            [(snapshot, STATUS_OK)],
            datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        )
        reset_credits = payload["accounts"][0]["reset_credits"]
        self.assertEqual(reset_credits["available_label"], "2 available")
        self.assertEqual(reset_credits["expires"], "7/12(日) 13:03、7/27(月) 9:39")

    def test_codex_reset_credits_omitted_when_zero(self) -> None:
        snapshot = _snapshot(remaining=54)
        snapshot = QuotaSnapshot(
            provider=snapshot.provider,
            email=snapshot.email,
            plan=snapshot.plan,
            chatgpt_account_id=snapshot.chatgpt_account_id,
            five_hour=snapshot.five_hour,
            weekly=snapshot.weekly,
            source=snapshot.source,
            updated_at=snapshot.updated_at,
            error=snapshot.error,
            primary=snapshot.primary,
            secondary=snapshot.secondary,
            primary_label=snapshot.primary_label,
            secondary_label=snapshot.secondary_label,
            provider_account_id=snapshot.provider_account_id,
            codex_reset_credits=CodexResetCredits(available_count=0, expires_at=()),
        )
        payload = build_payload(
            [(snapshot, STATUS_OK)],
            datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        )
        self.assertNotIn("reset_credits", payload["accounts"][0])

    def test_stale_rows_returns_cached_success(self) -> None:
        store = SnapshotStore()
        store.merge([_snapshot(remaining=54)])

        rows = store.stale_rows()

        self.assertEqual(rows[0][1], STATUS_STALE)


if __name__ == "__main__":
    unittest.main()
