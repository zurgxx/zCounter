from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from zcounter.models import QuotaSnapshot
from zcounter.notify.discord_webhook import send_discord_message

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")
DECREASE_NOTIFY_THRESHOLD = 1.0


def cursor_api_remaining_percent(snapshot: QuotaSnapshot) -> float | None:
    if snapshot.provider != "cursor" or snapshot.error is not None:
        return None
    if snapshot.tertiary is None:
        return None
    value = snapshot.tertiary.remaining_percent
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    return max(0.0, min(100.0, value))


def should_notify_api_decrease(previous: float | None, current: float) -> bool:
    if previous is None:
        return False
    return previous - current >= DECREASE_NOTIFY_THRESHOLD


def format_api_decrease_message(previous: float, current: float, recorded_at: datetime) -> str:
    previous_display = round(previous)
    current_display = round(current)
    delta = previous_display - current_display
    timestamp = recorded_at.astimezone(JST).strftime("%Y-%m-%d %H:%M JST")
    return (
        "⚠️ zCounter API usage decreased\n\n"
        f"Cursor API remaining: {previous_display}% → {current_display}% (-{delta}%)\n\n"
        f"{timestamp}"
    )


def maybe_notify_cursor_api_decrease(
    previous: float | None,
    snapshots: Sequence[QuotaSnapshot],
    recorded_at: datetime,
    *,
    webhook_url: str | None = None,
) -> float | None:
    current = None
    for snapshot in snapshots:
        if snapshot.provider == "cursor":
            current = cursor_api_remaining_percent(snapshot)
            break

    if current is None:
        return previous

    if should_notify_api_decrease(previous, current):
        try:
            send_discord_message(
                format_api_decrease_message(previous, current, recorded_at),
                webhook_url=webhook_url,
            )
        except Exception:
            logger.warning("failed to send cursor API usage notification", exc_info=True)

    return current
