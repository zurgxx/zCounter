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
    display_tertiary,
    format_daily_pace,
    format_reset_at,
    format_reset_credits_available_label,
    format_reset_credits_expires,
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
    if is_cursor(snapshot):
        return _cursor_account_payload(snapshot, status, now)

    primary = display_primary(snapshot)
    secondary = display_secondary(snapshot)
    metrics: list[dict[str, Any]] = []
    primary_metric = _metric_payload(snapshot.primary_label or "Primary", primary, now)
    if primary_metric is not None:
        metrics.append(primary_metric)
    secondary_metric = _metric_payload(
        snapshot.secondary_label or "Secondary",
        secondary,
        now,
    )
    if secondary_metric is not None:
        metrics.append(secondary_metric)
    level = _worst_level([metric["level"] for metric in metrics])
    if status == STATUS_ERROR:
        level = LEVEL_CRITICAL
    payload: dict[str, Any] = {
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
    reset_credits = _codex_reset_credits_payload(snapshot)
    if reset_credits is not None:
        payload["reset_credits"] = reset_credits
    return payload


def _codex_reset_credits_payload(snapshot: QuotaSnapshot) -> dict[str, str] | None:
    if snapshot.provider != "codex":
        return None
    credits = snapshot.codex_reset_credits
    if credits is None or credits.available_count <= 0:
        return None
    return {
        "available_label": format_reset_credits_available_label(credits.available_count),
        "expires": format_reset_credits_expires(credits.expires_at),
    }


def _cursor_account_payload(
    snapshot: QuotaSnapshot,
    status: str,
    now: datetime,
) -> dict[str, Any]:
    primary = display_primary(snapshot)
    secondary = display_secondary(snapshot)
    tertiary = display_tertiary(snapshot)
    cursor_pace_level = _cursor_pace_level(daily_pace_per_day(primary, now))
    level = cursor_pace_level or LEVEL_SAFE
    if status == STATUS_ERROR:
        level = LEVEL_CRITICAL

    total_metric = _metric_payload(snapshot.primary_label or "Total", primary, now, cursor=True)
    sub_metrics: list[dict[str, Any]] = []
    secondary_metric = _metric_payload(
        snapshot.secondary_label or "Auto(+Composer)",
        secondary,
        now,
        cursor=True,
    )
    if secondary_metric is not None:
        sub_metrics.append(secondary_metric)
    tertiary_metric = _metric_payload(
        snapshot.tertiary_label or "API",
        tertiary,
        now,
        cursor=True,
    )
    if tertiary_metric is not None:
        sub_metrics.append(tertiary_metric)

    cursor_layout: dict[str, Any] | None = None
    if total_metric is not None:
        cursor_layout = {
            "total": total_metric,
            "sub_metrics": sub_metrics,
            "footer": {
                "reset": format_reset_at(primary.reset_at, now) if primary else "-",
                "pace": format_daily_pace(primary, now),
                "pace_level": cursor_pace_level,
            },
        }

    return {
        "provider": snapshot.provider.title(),
        "account": _account_name(snapshot.email),
        "email": snapshot.email,
        "plan": _plan_label(snapshot.plan),
        "level": level,
        "status": status,
        "status_label": _status_label(status, level),
        "error": snapshot.error,
        "display_mode": "cursor-hero",
        "cursor": cursor_layout,
        "metrics": [],
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
