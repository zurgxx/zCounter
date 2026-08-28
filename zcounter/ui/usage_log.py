from __future__ import annotations

import math
import os
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from zcounter.models import QuotaSnapshot, RateWindow


USAGE_LOG_ENV = "ZCOUNTER_USAGE_LOG"
USAGE_LOG_FILENAME = "usage.log"

# Claude is currently hidden from the Web UI. Keep the log scope aligned with
# the accounts shown by build_payload while allowing the visible provider set
# and account count to change without changing this logger.
_HIDDEN_UI_PROVIDERS = frozenset({"claude"})
_TOKEN_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def usage_log_path() -> Path:
    override = os.environ.get(USAGE_LOG_ENV)
    if override:
        return Path(override).expanduser()

    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "zcounter" / USAGE_LOG_FILENAME
    return Path.home() / ".local" / "state" / "zcounter" / USAGE_LOG_FILENAME


def append_usage_log(
    snapshots: Sequence[QuotaSnapshot],
    recorded_at: datetime,
    path: Path | None = None,
) -> bool:
    line = format_usage_log_line(snapshots, recorded_at)
    if line is None:
        return False

    target = path or usage_log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        return False
    return True


def format_usage_log_line(
    snapshots: Sequence[QuotaSnapshot],
    recorded_at: datetime,
) -> str | None:
    target_snapshots = [
        snapshot
        for snapshot in snapshots
        if snapshot.provider not in _HIDDEN_UI_PROVIDERS
    ]
    if not target_snapshots:
        return None
    if any(snapshot.error is not None for snapshot in target_snapshots):
        return None

    account_parts: list[str] = []
    account_counts: dict[str, int] = {}
    for snapshot in target_snapshots:
        quotas = _quota_entries(snapshot)
        if not quotas:
            return None

        base_label = _account_label(snapshot)
        account_counts[base_label] = account_counts.get(base_label, 0) + 1
        label = base_label
        if account_counts[base_label] > 1:
            label = f"{base_label}-{account_counts[base_label]}"
        quota_text = ",".join(f"{name}={remaining:.0f}%" for name, remaining in quotas)
        account_parts.append(f"{label}:{quota_text}")

    timestamp = recorded_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return f"{timestamp} {' '.join(account_parts)}\n"


def _account_label(snapshot: QuotaSnapshot) -> str:
    if snapshot.email:
        label = snapshot.email.split("@", 1)[0]
    elif snapshot.provider_account_id:
        label = snapshot.provider_account_id
    else:
        label = snapshot.provider or "account"
    return _token(label) or "account"


def _quota_entries(snapshot: QuotaSnapshot) -> list[tuple[str, float]]:
    entries: list[tuple[str, float]] = []
    known_durations: set[tuple[int | None, int | None]] = set()
    known_windows: set[int] = set()

    for name in ("five_hour", "weekly"):
        window = getattr(snapshot, name)
        if window is None:
            continue
        remaining = _remaining_percent(window)
        if remaining is None:
            continue
        entries.append((name, remaining))
        known_windows.add(id(window))
        duration = _duration_key(window)
        if duration is not None:
            known_durations.add(duration)

    generic_windows = (
        ("primary", snapshot.primary, snapshot.primary_label),
        ("secondary", snapshot.secondary, snapshot.secondary_label),
        ("tertiary", snapshot.tertiary, snapshot.tertiary_label),
    )
    for fallback_name, window, label in generic_windows:
        if window is None:
            continue
        if id(window) in known_windows:
            continue
        duration = _duration_key(window)
        if duration is not None and duration in known_durations:
            continue
        remaining = _remaining_percent(window)
        if remaining is None:
            continue
        entries.append((_quota_token(label or fallback_name) or fallback_name, remaining))
        known_windows.add(id(window))
        if duration is not None:
            known_durations.add(duration)

    grok_remaining = _grok_bot_remaining_percent(snapshot)
    if grok_remaining is not None:
        entries.append(("grok_bot_weekly", grok_remaining))

    return entries


def _duration_key(window: RateWindow) -> tuple[int | None, int | None] | None:
    if window.window_seconds is None and window.window_minutes is None:
        return None
    return window.window_seconds, window.window_minutes


def _remaining_percent(window: RateWindow) -> float | None:
    value = window.remaining_percent
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    return max(0.0, min(100.0, value))


def _grok_bot_remaining_percent(snapshot: QuotaSnapshot) -> float | None:
    if snapshot.provider != "cursor" or not isinstance(snapshot.details, dict):
        return None
    grok_bot = snapshot.details.get("grok_bot")
    if not isinstance(grok_bot, dict):
        return None
    value = grok_bot.get("remaining_percent")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    return max(0.0, min(100.0, value))


def _token(value: str) -> str:
    return _TOKEN_RE.sub("_", value.strip()).strip("_")


def _quota_token(value: str) -> str:
    return _token(value).lower().replace("-", "_")
