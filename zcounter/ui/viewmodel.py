from __future__ import annotations

from datetime import datetime
from typing import Any

from zcounter.models import QuotaSnapshot, RateWindow
from zcounter.ui.display import (
    STATUS_ERROR,
    STATUS_OK,
    STATUS_STALE,
    account_key,
    display_primary,
    display_secondary,
    format_reset_at,
    merge_with_cache,
)

LEVEL_SAFE = "safe"
LEVEL_WARNING = "warning"
LEVEL_CRITICAL = "critical"


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
    accounts = [_account_payload(snapshot, status) for snapshot, status in rows]
    return {
        "accounts": accounts,
        "critical_count": sum(account["level"] == LEVEL_CRITICAL for account in accounts),
        "warning_count": sum(account["level"] == LEVEL_WARNING for account in accounts),
        "updated_at": updated_at.astimezone().isoformat(timespec="seconds"),
    }


def _account_payload(snapshot: QuotaSnapshot, status: str) -> dict[str, Any]:
    primary = display_primary(snapshot)
    secondary = display_secondary(snapshot)
    metrics = [
        _metric_payload(snapshot.primary_label or "Primary", primary),
        _metric_payload(snapshot.secondary_label or "Secondary", secondary),
    ]
    metrics = [metric for metric in metrics if metric is not None]
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


def _metric_payload(label: str, window: RateWindow | None) -> dict[str, Any] | None:
    if window is None:
        return None
    remaining = max(0.0, min(100.0, window.remaining_percent))
    return {
        "label": label,
        "remaining_percent": round(remaining),
        "level": _remaining_level(remaining),
        "reset": format_reset_at(window.reset_at),
    }


def _remaining_level(remaining: float) -> str:
    if remaining < 10:
        return LEVEL_CRITICAL
    if remaining < 20:
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
