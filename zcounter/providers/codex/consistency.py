from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from zcounter.models import QuotaSnapshot, RateWindow
from zcounter.providers.codex.usage_api import (
    FIVE_HOUR_SECONDS,
    WEEK_SECONDS,
    rebuild_codex_display,
    window_label_from_seconds,
)


# Heuristic for transient near-zero values from OpenAI wham/usage.  Small
# decreases are valid API behaviour and must not be treated as resets.
SUSPICIOUS_USED_PERCENT_MAX = 1.0
SUSPICIOUS_DROP_MIN_POINTS = 20.0


def preserve_unreset_codex_windows(
    cached: QuotaSnapshot | None,
    fresh: QuotaSnapshot,
    *,
    now: datetime,
) -> QuotaSnapshot:
    """Keep per-window Codex values when a likely transient reset is observed.

    The caller owns the lifetime of ``cached``.  This function deliberately
    does not persist values itself, and only changes successful Codex usage
    snapshots; transport and shape failures continue through normal stale
    handling.
    """
    if cached is None or fresh.provider != "codex" or fresh.error is not None:
        return fresh

    five_hour, held_five_hour = _preserve_window(
        cached.five_hour,
        fresh.five_hour,
        now,
    )
    weekly, held_weekly = _preserve_window(cached.weekly, fresh.weekly, now)
    if not held_five_hour and not held_weekly:
        return fresh

    warnings = list(fresh.warnings)
    if held_five_hour:
        _append_warning(
            warnings,
            _retention_warning(cached.five_hour),
        )
    if held_weekly:
        _append_warning(
            warnings,
            _retention_warning(cached.weekly),
        )

    extra = _extra_display_windows(fresh)
    primary, secondary, primary_label, secondary_label = rebuild_codex_display(
        five_hour,
        weekly,
        *extra,
    )
    return replace(
        fresh,
        five_hour=five_hour,
        weekly=weekly,
        primary=primary,
        secondary=secondary,
        primary_label=primary_label,
        secondary_label=secondary_label,
        warnings=tuple(warnings),
    )


def _retention_warning(window: RateWindow | None) -> str:
    label = window_label_from_seconds(window.window_seconds if window else None)
    return (
        f"Codex {label} usage near zero without reset evidence; "
        "previous value retained"
    )


def _extra_display_windows(snapshot: QuotaSnapshot) -> tuple[RateWindow, ...]:
    extras: list[RateWindow] = []
    for window in (snapshot.primary, snapshot.secondary):
        if window is None:
            continue
        if window.window_seconds in (FIVE_HOUR_SECONDS, WEEK_SECONDS):
            continue
        extras.append(window)
    return tuple(extras)


def _append_warning(warnings: list[str], warning: str) -> None:
    if warning not in warnings:
        warnings.append(warning)


def _preserve_window(
    previous: RateWindow | None,
    current: RateWindow | None,
    now: datetime,
) -> tuple[RateWindow | None, bool]:
    if previous is None or current is None:
        return current, False
    if previous.window_seconds != current.window_seconds:
        return current, False
    if not _is_unreset_near_zero_drop(previous, current, now):
        return current, False
    return previous, True


def _is_unreset_near_zero_drop(
    previous: RateWindow,
    current: RateWindow,
    now: datetime,
) -> bool:
    previous_reset = previous.reset_at
    current_reset = current.reset_at
    if previous_reset is None or current_reset is None:
        return False
    if now >= previous_reset:
        return False
    if current_reset > previous_reset:
        return False
    if current.used_percent > SUSPICIOUS_USED_PERCENT_MAX:
        return False
    return previous.used_percent - current.used_percent >= SUSPICIOUS_DROP_MIN_POINTS
