from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from zcounter.models import QuotaSnapshot, RateWindow, utc_now

JST = ZoneInfo("Asia/Tokyo")

LEVEL_NORMAL = "normal"
LEVEL_WARNING = "warning"
LEVEL_DANGER = "danger"

STATUS_OK = "ok"
STATUS_STALE = "stale"
STATUS_ERROR = "error"

EMAIL_WIDTH = 20
CURSOR_QUOTA_WIDTH = 38
REFRESH_SECONDS = 300


def account_key(snapshot: QuotaSnapshot) -> str:
    if snapshot.provider_account_id:
        return f"{snapshot.provider}:{snapshot.provider_account_id}"
    if snapshot.chatgpt_account_id:
        return f"{snapshot.provider}:{snapshot.chatgpt_account_id}"
    if snapshot.email:
        return f"{snapshot.provider}:{snapshot.email}"
    return f"{snapshot.provider}:unknown"


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
        primary=fresh.primary or cached.primary or fresh.five_hour or cached.five_hour,
        secondary=fresh.secondary or cached.secondary or fresh.weekly or cached.weekly,
        primary_label=fresh.primary_label or cached.primary_label,
        secondary_label=fresh.secondary_label or cached.secondary_label,
        provider_account_id=fresh.provider_account_id or cached.provider_account_id,
        warnings=fresh.warnings or cached.warnings,
        details=fresh.details or cached.details,
    )
    if merged.primary is not None or merged.secondary is not None:
        return merged, STATUS_STALE
    return fresh, STATUS_ERROR


def remaining_level(window: RateWindow | None) -> str:
    if window is None:
        return LEVEL_NORMAL
    remaining = window.remaining_percent
    if remaining < 20:
        return LEVEL_DANGER
    if remaining < 40:
        return LEVEL_WARNING
    return LEVEL_NORMAL


def format_percent(window: RateWindow | None) -> str:
    if window is None:
        return "--"
    return f"{window.remaining_percent:.0f}%"


def format_updated_at_jst(value: datetime) -> str:
    local = _to_jst(value)
    return (
        f"{local.year}/{local.month}/{local.day} "
        f"{local.hour}:{local.minute:02d}:{local.second:02d} JST"
    )


def format_updated_footer(updated_at: datetime, refresh_seconds: int = REFRESH_SECONDS) -> str:
    stamp = format_updated_at_jst(updated_at)
    return f"updated {stamp} : refresh {refresh_seconds}s"


def format_cursor_billing_reset(reset_at: datetime | None) -> str:
    if reset_at is None:
        return "-"
    local_reset = reset_at.astimezone()
    date_part = f"{local_reset.year}/{local_reset.month}/{local_reset.day}"
    time_part = f"{local_reset.hour}:{local_reset.minute:02d}"
    return f"{date_part} {time_part}"


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


def format_daily_pace(window: RateWindow | None, now: datetime | None = None) -> str:
    if window is None:
        return "-"
    reset_at = window.reset_at
    if reset_at is None:
        return "-"
    current = _local_now(now)
    local_reset = reset_at.astimezone()
    if local_reset <= current:
        return "now"
    remaining_days = (local_reset - current).total_seconds() / 86400
    if remaining_days <= 0:
        return "now"
    pace = window.remaining_percent / remaining_days
    return f"{pace:.1f}%/d"


def is_cursor(snapshot: QuotaSnapshot) -> bool:
    return snapshot.provider == "cursor"


def format_cursor_row(snapshot: QuotaSnapshot) -> str:
    email = format_email(snapshot.email, width=EMAIL_WIDTH)
    primary = display_primary(snapshot)
    secondary = display_secondary(snapshot)
    total = f"Total {format_percent(primary)}"
    auto = f"Auto {format_percent(secondary)}"
    reset = format_cursor_billing_reset(
        primary.reset_at if primary is not None else None,
    )
    quota = f"{total} {auto} {reset}".ljust(CURSOR_QUOTA_WIDTH)
    return f"{email}{quota}"


def format_codex_row(snapshot: QuotaSnapshot, now: datetime | None = None) -> str:
    email = format_email(snapshot.email, width=EMAIL_WIDTH)
    primary = display_primary(snapshot)
    secondary = display_secondary(snapshot)
    primary_pct = format_percent(primary)
    primary_reset = format_reset_time(primary, now)
    secondary_pct = format_percent(secondary)
    secondary_reset = format_reset_time(secondary, now)
    primary_label = format_window_label(snapshot.primary_label, "P")
    secondary_label = format_window_label(snapshot.secondary_label, "S")
    return f"{email}{primary_label} {primary_pct:>3} {primary_reset}  {secondary_label} {secondary_pct:>3} {secondary_reset}"


def format_account_row(snapshot: QuotaSnapshot, now: datetime | None = None) -> str:
    if is_cursor(snapshot):
        return format_cursor_row(snapshot)
    return format_codex_row(snapshot, now)


def format_status_suffix(status: str, snapshot: QuotaSnapshot) -> str:
    if is_cursor(snapshot):
        if status == STATUS_STALE:
            return "stale"
        return ""
    if status == STATUS_STALE:
        return "stale"
    if status == STATUS_ERROR and snapshot.error:
        return _truncate(snapshot.error, 40)
    if snapshot.warnings:
        return _truncate(snapshot.warnings[0], 40)
    return ""


def display_primary(snapshot: QuotaSnapshot) -> RateWindow | None:
    return snapshot.primary or snapshot.five_hour


def display_secondary(snapshot: QuotaSnapshot) -> RateWindow | None:
    return snapshot.secondary or snapshot.weekly


def format_window_label(label: str | None, fallback: str) -> str:
    value = label or fallback
    return value[:5].ljust(5)


def format_email(email: str | None, width: int = EMAIL_WIDTH) -> str:
    label = email or "-"
    if len(label) <= width:
        return label.ljust(width)
    return label[: width - 1] + "…"


def _to_jst(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(JST)


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
