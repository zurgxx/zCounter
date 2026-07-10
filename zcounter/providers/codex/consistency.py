from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from zcounter.models import QuotaSnapshot, RateWindow


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
            "Codex 5H usage near zero without reset evidence; previous value retained",
        )
    if held_weekly:
        _append_warning(
            warnings,
            "Codex weekly usage near zero without reset evidence; previous value retained",
        )

    return replace(
        fresh,
        five_hour=five_hour,
        weekly=weekly,
        # Codex provider snapshots expose the same two windows through the
        # generic primary/secondary aliases used by the UI and CLI.
        primary=five_hour if fresh.primary is not None else None,
        secondary=weekly if fresh.secondary is not None else None,
        warnings=tuple(warnings),
    )


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
