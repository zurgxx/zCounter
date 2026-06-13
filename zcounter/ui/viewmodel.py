from __future__ import annotations

from datetime import datetime
from typing import Any

from zcounter.models import QuotaSnapshot, RateWindow
from zcounter.ui.display import (
    STATUS_ERROR,
    STATUS_OK,
    STATUS_STALE,
    account_key,
    daily_pace_per_day,
    display_primary,
    display_secondary,
    format_daily_pace,
    format_reset_at,
    is_cursor,
    merge_with_cache,
)

LEVEL_SAFE = "safe"
LEVEL_WARNING = "warning"
LEVEL_CRITICAL = "critical"

CURSOR_PACE_WARNING = 3.0
CURSOR_PACE_CRITICAL = 1.0


class SnapshotStore:
    def __init__(self) -> None:
        self._cache: dict[str, QuotaSnapshot] = {}

    def merge(self, snapshots: list[QuotaSnapshot]) -> list[tuple[QuotaSnapshot, str]]:
        rows: list[tuple[QuotaSnapshot, str]] = []
        for snapshot in snapshots:
            key = account_key(snapshot)
            cached = self._cache.get(key)
            if cached is None and snapshot.error:
                cached = self._single_provider_cache(snapshot.provider)
            merged, status = merge_with_cache(cached, snapshot)
            if status in (STATUS_OK, STATUS_STALE):
                self._cache[account_key(merged)] = merged
            rows.append((merged, status))
        return rows

    def stale_rows(self) -> list[tuple[QuotaSnapshot, str]]:
        return [(snapshot, STATUS_STALE) for snapshot in self._cache.values()]

    def _single_provider_cache(self, provider: str) -> QuotaSnapshot | None:
        candidates = [
            snapshot for snapshot in self._cache.values() if snapshot.provider == provider
        ]
        if len(candidates) == 1:
            return candidates[0]
        return None


def build_payload(
    rows: list[tuple[QuotaSnapshot, str]],
    updated_at: datetime,
) -> dict[str, Any]:
    accounts = [_account_payload(snapshot, status, updated_at) for snapshot, status in rows]
    return {
        "accounts": accounts,
        "critical_count": sum(account["level"] == LEVEL_CRITICAL for account in accounts),
        "warning_count": sum(account["level"] == LEVEL_WARNING for account in accounts),
        "updated_at": updated_at.astimezone().isoformat(timespec="seconds"),
    }


def _account_payload(
    snapshot: QuotaSnapshot,
    status: str,
    now: datetime,
) -> dict[str, Any]:
    primary = display_primary(snapshot)
    secondary = display_secondary(snapshot)
    metrics: list[dict[str, Any]] = []
    cursor = is_cursor(snapshot)
    cursor_pace_level = (
        _cursor_pace_level(daily_pace_per_day(primary, now)) if cursor else None
    )
    primary_metric = _metric_payload(snapshot.primary_label or "Primary", primary, now, cursor=cursor)
    if primary_metric is not None:
        metrics.append(primary_metric)
    secondary_metric = _metric_payload(
        snapshot.secondary_label or "Secondary",
        secondary,
        now,
        cursor=cursor,
    )
    if secondary_metric is not None:
        if cursor:
            secondary_metric["reset"] = "-"
            secondary_metric["pace"] = format_daily_pace(primary, now)
            secondary_metric["pace_level"] = cursor_pace_level
        metrics.append(secondary_metric)
    if cursor:
        level = cursor_pace_level or LEVEL_SAFE
    else:
        level = _worst_level([metric["level"] for metric in metrics])
    if status == STATUS_ERROR:
        level = LEVEL_CRITICAL
    return {
        "provider": snapshot.provider.title(),
        "account": _account_name(snapshot.email),
        "email": snapshot.email,
        "plan": _plan_label(snapshot.plan),
        "level": level,
        "status": status,
        "status_label": _status_label(status, level),
        "error": snapshot.error,
        "metrics": metrics,
    }


def _metric_payload(
    label: str,
    window: RateWindow | None,
    now: datetime,
    *,
    cursor: bool = False,
) -> dict[str, Any] | None:
    if window is None:
        return None
    remaining = max(0.0, min(100.0, window.remaining_percent))
    level = LEVEL_SAFE if cursor else _remaining_level(remaining)
    return {
        "label": label,
        "remaining_percent": round(remaining),
        "level": level,
        "reset": format_reset_at(window.reset_at, now),
    }


def _cursor_pace_level(pace: float | None) -> str:
    if pace is None:
        return LEVEL_SAFE
    if pace < CURSOR_PACE_CRITICAL:
        return LEVEL_CRITICAL
    if pace < CURSOR_PACE_WARNING:
        return LEVEL_WARNING
    return LEVEL_SAFE


def _remaining_level(remaining: float) -> str:
    if remaining < 20:
        return LEVEL_CRITICAL
    if remaining < 40:
        return LEVEL_WARNING
    return LEVEL_SAFE


def _worst_level(levels: list[str]) -> str:
    for level in (LEVEL_CRITICAL, LEVEL_WARNING):
        if level in levels:
            return level
    return LEVEL_SAFE


def _status_label(status: str, level: str) -> str:
    if status == STATUS_STALE:
        return "Stale"
    if status == STATUS_ERROR:
        return "Error"
    return level.title()


def _account_name(email: str | None) -> str:
    if not email:
        return "-"
    return email.split("@", 1)[0]


def _plan_label(plan: str | None) -> str:
    if not plan:
        return "-"
    return plan[:1].upper() + plan[1:]
