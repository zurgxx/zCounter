from __future__ import annotations

from datetime import datetime, timezone

from zcounter.models import QuotaSnapshot, RateWindow, utc_now

LEVEL_NORMAL = "normal"
LEVEL_WARNING = "warning"
LEVEL_DANGER = "danger"

STATUS_OK = "ok"
STATUS_STALE = "stale"
STATUS_ERROR = "error"

EMAIL_WIDTH = 18


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


def format_reset_at(reset_at: datetime | None, now: datetime | None = None) -> str:
    if reset_at is None:
        return "-"
    current = _local_now(now)
    local_reset = reset_at.astimezone()
    if local_reset <= current:
        return "now"
    if local_reset.date() == current.date():
        return local_reset.strftime("%H:%M")
    date_part = f"{local_reset.year}/{local_reset.month}/{local_reset.day}"
    time_part = f"{local_reset.hour}:{local_reset.minute:02d}"
    return f"{date_part}  {time_part}"


def format_reset_time(window: RateWindow | None, now: datetime | None = None) -> str:
    if window is None:
        return "-"
    return format_reset_at(window.reset_at, now)


def format_account_row(snapshot: QuotaSnapshot, now: datetime | None = None) -> str:
    email = format_email(snapshot.email, width=EMAIL_WIDTH)
    five_pct = format_percent(snapshot.five_hour)
    five_reset = format_reset_time(snapshot.five_hour, now)
    wk_pct = format_percent(snapshot.weekly)
    wk_reset = format_reset_time(snapshot.weekly, now)
    return f"{email}5H {five_pct:>3} {five_reset}  WK {wk_pct:>3} {wk_reset}"


def format_status_suffix(status: str, snapshot: QuotaSnapshot) -> str:
    if status == STATUS_STALE:
        return "stale"
    if status == STATUS_ERROR and snapshot.error:
        return _truncate(snapshot.error, 40)
    return ""


def format_email(email: str | None, width: int = EMAIL_WIDTH) -> str:
    label = email or "-"
    if len(label) <= width:
        return label.ljust(width)
    return label[: width - 1] + "…"


def _local_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now().astimezone()
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc).astimezone()
    return now.astimezone()


def _truncate(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    return value[: max_len - 1] + "…"
