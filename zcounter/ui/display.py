from __future__ import annotations

from datetime import datetime, timedelta

from zcounter.models import QuotaSnapshot, RateWindow, utc_now

LEVEL_NORMAL = "normal"
LEVEL_WARNING = "warning"
LEVEL_DANGER = "danger"

STATUS_OK = "ok"
STATUS_STALE = "stale"
STATUS_ERROR = "error"


def account_key(snapshot: QuotaSnapshot) -> str:
    if snapshot.chatgpt_account_id:
        return snapshot.chatgpt_account_id
    if snapshot.email:
        return snapshot.email
    return "unknown"


def merge_with_cache(
    cached: QuotaSnapshot | None,
    fresh: QuotaSnapshot,
) -> tuple[QuotaSnapshot, str]:
    if fresh.error is None:
        return fresh, STATUS_OK

    if cached is None:
        return fresh, STATUS_ERROR

    merged = QuotaSnapshot(
        provider=fresh.provider,
        email=fresh.email or cached.email,
        plan=fresh.plan or cached.plan,
        chatgpt_account_id=fresh.chatgpt_account_id or cached.chatgpt_account_id,
        five_hour=fresh.five_hour or cached.five_hour,
        weekly=fresh.weekly or cached.weekly,
        source=fresh.source,
        updated_at=fresh.updated_at,
        error=fresh.error,
    )
    if merged.five_hour is not None or merged.weekly is not None:
        return merged, STATUS_STALE
    return fresh, STATUS_ERROR


def remaining_level(window: RateWindow | None) -> str:
    if window is None:
        return LEVEL_NORMAL
    remaining = window.remaining_percent
    if remaining < 10:
        return LEVEL_DANGER
    if remaining < 20:
        return LEVEL_WARNING
    return LEVEL_NORMAL


def format_percent(window: RateWindow | None) -> str:
    if window is None:
        return "--"
    return f"{window.remaining_percent:.0f}%"


def format_reset(window: RateWindow | None, now: datetime | None = None) -> str | None:
    if window is None or window.reset_at is None:
        return None
    current = now or utc_now()
    delta = window.reset_at - current
    if delta.total_seconds() <= 0:
        return "now"
    return _format_timedelta(delta)


def format_reset_hint(snapshot: QuotaSnapshot, now: datetime | None = None) -> str:
    parts: list[str] = []
    five_hour_reset = format_reset(snapshot.five_hour, now)
    weekly_reset = format_reset(snapshot.weekly, now)
    if five_hour_reset is not None:
        parts.append(f"5H~{five_hour_reset}")
    if weekly_reset is not None:
        parts.append(f"WK~{weekly_reset}")
    if parts:
        return " ".join(parts)
    return "-"


def format_status_suffix(status: str, snapshot: QuotaSnapshot) -> str:
    if status == STATUS_STALE:
        return "stale"
    if status == STATUS_ERROR and snapshot.error:
        return _truncate(snapshot.error, 40)
    return ""


def format_email(email: str | None, width: int = 28) -> str:
    label = email or "-"
    if len(label) <= width:
        return label.ljust(width)
    return label[: width - 1] + "…"


def _format_timedelta(delta: timedelta) -> str:
    total_minutes = int(delta.total_seconds() // 60)
    if total_minutes < 60:
        return f"{total_minutes}m"
    hours, minutes = divmod(total_minutes, 60)
    if hours < 48:
        return f"{hours}h{minutes:02d}m" if minutes else f"{hours}h"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours}h" if hours else f"{days}d"


def _truncate(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    return value[: max_len - 1] + "…"
