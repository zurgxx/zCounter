from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from zcounter.models import QuotaSnapshot, RateWindow
from zcounter.providers.codex.consistency import preserve_unreset_codex_windows
from zcounter.providers.codex.usage_api import rebuild_codex_display
from zcounter.ui.display import STATUS_OK, STATUS_STALE
from zcounter.ui.viewmodel import SnapshotStore


NOW = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
RESET = NOW + timedelta(hours=4)
FIVE_HOUR_SECONDS = 18_000
WEEK_SECONDS = 604_800


def _window(
    used: float | None,
    reset: datetime | None = RESET,
    *,
    seconds: int = FIVE_HOUR_SECONDS,
) -> RateWindow | None:
    if used is None:
        return None
    return RateWindow(used, 100.0 - used, reset, seconds // 60, seconds)


def _snapshot(
    *,
    five_hour: float | None = 65,
    weekly: float | None = 50,
    five_hour_reset: datetime | None = RESET,
    weekly_reset: datetime | None = RESET + timedelta(days=6),
    updated_at: datetime = NOW,
    error: str | None = None,
    account_id: str = "account-id",
    warnings: tuple[str, ...] = (),
) -> QuotaSnapshot:
    five_hour_window = None if error or five_hour is None else _window(
        five_hour,
        five_hour_reset,
        seconds=FIVE_HOUR_SECONDS,
    )
    weekly_window = None if error or weekly is None else _window(
        weekly,
        weekly_reset,
        seconds=WEEK_SECONDS,
    )
    primary, secondary, primary_label, secondary_label = rebuild_codex_display(
        five_hour_window,
        weekly_window,
    )
    return QuotaSnapshot(
        provider="codex",
        email=f"{account_id}@example.com",
        plan="plus",
        chatgpt_account_id=account_id,
        five_hour=five_hour_window,
        weekly=weekly_window,
        source="wham-usage",
        updated_at=updated_at,
        error=error,
        primary=primary,
        secondary=secondary,
        primary_label=primary_label,
        secondary_label=secondary_label,
        provider_account_id=account_id,
        warnings=warnings,
    )


class CodexConsistencyTests(unittest.TestCase):
    def _reconcile(self, previous: QuotaSnapshot, current: QuotaSnapshot) -> QuotaSnapshot:
        return preserve_unreset_codex_windows(previous, current, now=current.updated_at)

    def test_initial_zero_usage_is_accepted(self) -> None:
        current = _snapshot(five_hour=0, weekly=0)

        result = preserve_unreset_codex_windows(None, current, now=NOW)

        self.assertEqual(result.five_hour.used_percent, 0)
        self.assertEqual(result.weekly.used_percent, 0)

    def test_same_reset_near_zero_drop_keeps_previous_window(self) -> None:
        result = self._reconcile(_snapshot(five_hour=65), _snapshot(five_hour=0))

        self.assertEqual(result.five_hour.used_percent, 65)
        self.assertEqual(result.primary.used_percent, 65)
        self.assertTrue(result.warnings)

    def test_threshold_boundaries_are_inclusive(self) -> None:
        result = self._reconcile(_snapshot(five_hour=21), _snapshot(five_hour=1))

        self.assertEqual(result.five_hour.used_percent, 21)

    def test_earlier_current_reset_is_not_reset_evidence(self) -> None:
        result = self._reconcile(
            _snapshot(five_hour=65),
            _snapshot(five_hour=0, five_hour_reset=RESET - timedelta(seconds=1)),
        )

        self.assertEqual(result.five_hour.used_percent, 65)

    def test_repeated_anomalous_zero_is_not_accepted_before_reset_boundary(self) -> None:
        previous = _snapshot(five_hour=65)
        first = self._reconcile(previous, _snapshot(five_hour=0))
        second = self._reconcile(first, _snapshot(five_hour=0, updated_at=NOW + timedelta(minutes=5)))

        self.assertEqual(first.five_hour.used_percent, 65)
        self.assertEqual(second.five_hour.used_percent, 65)

    def test_advanced_reset_accepts_zero_usage(self) -> None:
        result = self._reconcile(
            _snapshot(five_hour=65),
            _snapshot(five_hour=0, five_hour_reset=RESET + timedelta(hours=5)),
        )

        self.assertEqual(result.five_hour.used_percent, 0)

    def test_elapsed_previous_reset_accepts_zero_usage(self) -> None:
        result = self._reconcile(
            _snapshot(five_hour=65),
            _snapshot(five_hour=0, updated_at=RESET + timedelta(seconds=1)),
        )

        self.assertEqual(result.five_hour.used_percent, 0)

    def test_exact_previous_reset_boundary_accepts_zero_usage(self) -> None:
        result = self._reconcile(
            _snapshot(five_hour=65),
            _snapshot(five_hour=0, updated_at=RESET),
        )

        self.assertEqual(result.five_hour.used_percent, 0)

    def test_primary_anomaly_does_not_replace_secondary(self) -> None:
        result = self._reconcile(
            _snapshot(five_hour=65, weekly=70),
            _snapshot(five_hour=0, weekly=80),
        )

        self.assertEqual(result.five_hour.used_percent, 65)
        self.assertEqual(result.weekly.used_percent, 80)

    def test_secondary_anomaly_does_not_replace_primary(self) -> None:
        result = self._reconcile(
            _snapshot(five_hour=65, weekly=70),
            _snapshot(five_hour=80, weekly=0),
        )

        self.assertEqual(result.five_hour.used_percent, 80)
        self.assertEqual(result.weekly.used_percent, 70)

    def test_both_anomalies_keep_their_own_previous_windows(self) -> None:
        result = self._reconcile(
            _snapshot(five_hour=65, weekly=70),
            _snapshot(five_hour=0, weekly=0),
        )

        self.assertEqual(result.five_hour.used_percent, 65)
        self.assertEqual(result.weekly.used_percent, 70)

    def test_missing_window_keeps_existing_partial_response_behavior(self) -> None:
        result = self._reconcile(_snapshot(five_hour=65), _snapshot(five_hour=None, weekly=40))

        self.assertIsNone(result.five_hour)
        self.assertEqual(result.weekly.used_percent, 40)

    def test_normal_increase_and_small_decrease_are_accepted(self) -> None:
        increased = self._reconcile(_snapshot(five_hour=65), _snapshot(five_hour=80))
        small_drop = self._reconcile(_snapshot(five_hour=65), _snapshot(five_hour=55))

        self.assertEqual(increased.five_hour.used_percent, 80)
        self.assertEqual(small_drop.five_hour.used_percent, 55)

    def test_store_keeps_accounts_separate(self) -> None:
        store = SnapshotStore()
        store.merge([
            _snapshot(five_hour=65, account_id="account-a"),
            _snapshot(five_hour=10, account_id="account-b"),
        ])

        rows = store.merge([
            _snapshot(five_hour=0, account_id="account-a"),
            _snapshot(five_hour=0, account_id="account-b"),
        ])

        by_account = {snapshot.provider_account_id: snapshot for snapshot, _ in rows}
        self.assertEqual(by_account["account-a"].five_hour.used_percent, 65)
        self.assertEqual(by_account["account-b"].five_hour.used_percent, 0)

    def test_store_keeps_cached_values_for_api_error(self) -> None:
        store = SnapshotStore()
        store.merge([_snapshot(five_hour=65, weekly=70)])

        rows = store.merge([_snapshot(error="request failed")])

        snapshot, status = rows[0]
        self.assertEqual(status, STATUS_STALE)
        self.assertEqual(snapshot.five_hour.used_percent, 65)
        self.assertEqual(snapshot.weekly.used_percent, 70)

    def test_store_applies_consistency_guard_before_successful_cache_replacement(self) -> None:
        store = SnapshotStore()
        store.merge([_snapshot(five_hour=65, weekly=70)])

        rows = store.merge([_snapshot(five_hour=0, weekly=80)])

        snapshot, status = rows[0]
        self.assertEqual(status, STATUS_OK)
        self.assertEqual(snapshot.five_hour.used_percent, 65)
        self.assertEqual(snapshot.weekly.used_percent, 80)

    def test_existing_warning_is_not_duplicated(self) -> None:
        warning = (
            "Codex 5H usage near zero without reset evidence; previous value retained"
        )
        result = self._reconcile(
            _snapshot(five_hour=65),
            _snapshot(five_hour=0, warnings=(warning,)),
        )

        self.assertEqual(result.warnings, (warning,))

    def test_different_duration_windows_are_not_cross_preserved(self) -> None:
        previous = _snapshot(five_hour=65, weekly=None)
        current = QuotaSnapshot(
            provider="codex",
            email=previous.email,
            plan=previous.plan,
            chatgpt_account_id=previous.chatgpt_account_id,
            five_hour=None,
            weekly=_window(0, RESET + timedelta(days=6), seconds=WEEK_SECONDS),
            source="wham-usage",
            updated_at=NOW,
            error=None,
            primary=_window(0, RESET + timedelta(days=6), seconds=WEEK_SECONDS),
            secondary=None,
            primary_label="WEEK",
            secondary_label=None,
            provider_account_id=previous.provider_account_id,
        )

        result = self._reconcile(previous, current)

        self.assertIsNone(result.five_hour)
        self.assertEqual(result.weekly.used_percent, 0)
        self.assertEqual(result.primary_label, "WEEK")
        self.assertFalse(result.warnings)


if __name__ == "__main__":
    unittest.main()
