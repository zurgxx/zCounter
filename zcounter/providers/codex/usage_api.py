from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from zcounter.models import CodexResetCredits, RateWindow, parse_iso_datetime, parse_unix_timestamp, utc_now


USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
RESET_CREDITS_URL = "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits"

FIVE_HOUR_SECONDS = 18_000
WEEK_SECONDS = 604_800
DAY_SECONDS = 86_400
HOUR_SECONDS = 3_600


class UsageAPIError(Exception):
    pass


class UnauthorizedError(UsageAPIError):
    pass


class UsageShapeError(UsageAPIError):
    pass


class WindowShapeError(Exception):
    pass


@dataclass(frozen=True)
class CodexUsageNormalized:
    five_hour: RateWindow | None
    weekly: RateWindow | None
    primary: RateWindow | None
    secondary: RateWindow | None
    primary_label: str | None
    secondary_label: str | None


def fetch_usage(
    access_token: str,
    account_id: str,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    request = urllib.request.Request(
        USAGE_URL,
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "ChatGPT-Account-Id": account_id,
            "User-Agent": "zCounter/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise UnauthorizedError(f"usage API returned HTTP {exc.code}") from exc
        raise UsageAPIError(f"usage API returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise UsageAPIError(f"usage API request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise UsageAPIError("usage API request timed out") from exc

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UsageShapeError("usage API response is not valid JSON") from exc
    if not isinstance(data, dict):
        raise UsageShapeError("usage API response root is not an object")
    return data


def fetch_rate_limit_reset_credits(
    access_token: str,
    account_id: str,
    timeout_seconds: float = 4.0,
) -> dict[str, Any]:
    request = urllib.request.Request(
        RESET_CREDITS_URL,
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "ChatGPT-Account-Id": account_id,
            "OpenAI-Beta": "codex-1",
            "originator": "Codex Desktop",
            "User-Agent": "zCounter/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise UnauthorizedError(f"reset credits API returned HTTP {exc.code}") from exc
        raise UsageAPIError(f"reset credits API returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise UsageAPIError(f"reset credits API request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise UsageAPIError("reset credits API request timed out") from exc

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UsageShapeError("reset credits API response is not valid JSON") from exc
    if not isinstance(data, dict):
        raise UsageShapeError("reset credits API response root is not an object")
    return data


def normalize_reset_credits_response(
    data: dict[str, Any],
    *,
    now: datetime | None = None,
) -> CodexResetCredits | None:
    credits = data.get("credits")
    available_count = data.get("available_count")
    if not isinstance(credits, list):
        return None
    if not isinstance(available_count, int) or available_count < 0:
        return None

    current = now or utc_now()
    expires_at: list = []
    for raw in credits:
        if not isinstance(raw, dict) or raw.get("status") != "available":
            continue
        expires = parse_iso_datetime(raw.get("expires_at"))
        if expires is None:
            continue
        if expires <= current:
            continue
        expires_at.append(expires)
    expires_at.sort()
    return CodexResetCredits(available_count=available_count, expires_at=tuple(expires_at))


def window_label_from_seconds(seconds: int | None) -> str:
    if seconds is None:
        return "WINDOW"
    if seconds == FIVE_HOUR_SECONDS:
        return "5H"
    if seconds == WEEK_SECONDS:
        return "WEEK"
    if seconds % DAY_SECONDS == 0:
        return f"{seconds // DAY_SECONDS}D"
    if seconds % HOUR_SECONDS == 0:
        return f"{seconds // HOUR_SECONDS}H"
    return "WINDOW"


def normalize_codex_usage(data: dict[str, Any]) -> CodexUsageNormalized:
    rate_limit = data.get("rate_limit")
    if not isinstance(rate_limit, dict):
        raise UsageShapeError("usage API response missing rate_limit object")

    windows = _parse_rate_limit_windows(rate_limit)
    if not windows:
        raise UsageShapeError("usage API response contains no rate limit windows")

    five_hour = _window_by_seconds(windows, FIVE_HOUR_SECONDS)
    weekly = _window_by_seconds(windows, WEEK_SECONDS)
    primary, secondary, primary_label, secondary_label = build_codex_display_slots(windows)
    return CodexUsageNormalized(
        five_hour=five_hour,
        weekly=weekly,
        primary=primary,
        secondary=secondary,
        primary_label=primary_label,
        secondary_label=secondary_label,
    )


def normalize_usage_response(data: dict[str, Any]) -> tuple[RateWindow | None, RateWindow | None]:
    normalized = normalize_codex_usage(data)
    return normalized.five_hour, normalized.weekly


def build_codex_display_slots(
    windows: list[RateWindow],
) -> tuple[RateWindow | None, RateWindow | None, str | None, str | None]:
    if not windows:
        return None, None, None, None
    ordered = sorted(windows, key=lambda window: window.window_seconds or 0)
    primary = ordered[0]
    secondary = ordered[1] if len(ordered) > 1 else None
    primary_label = window_label_from_seconds(primary.window_seconds)
    secondary_label = (
        window_label_from_seconds(secondary.window_seconds) if secondary is not None else None
    )
    return primary, secondary, primary_label, secondary_label


def rebuild_codex_display(
    five_hour: RateWindow | None,
    weekly: RateWindow | None,
    *extra: RateWindow | None,
) -> tuple[RateWindow | None, RateWindow | None, str | None, str | None]:
    windows = _unique_windows(five_hour, weekly, *extra)
    return build_codex_display_slots(windows)


def _parse_rate_limit_windows(rate_limit: dict[str, Any]) -> list[RateWindow]:
    windows: list[RateWindow] = []
    for key in ("primary_window", "secondary_window"):
        window = _parse_window_lenient(rate_limit.get(key))
        if window is not None:
            windows.append(window)
    return windows


def _window_by_seconds(windows: list[RateWindow], seconds: int) -> RateWindow | None:
    for window in windows:
        if window.window_seconds == seconds:
            return window
    return None


def _unique_windows(*candidates: RateWindow | None) -> list[RateWindow]:
    windows: list[RateWindow] = []
    for candidate in candidates:
        if candidate is None:
            continue
        if any(_same_window(existing, candidate) for existing in windows):
            continue
        windows.append(candidate)
    return windows


def _same_window(left: RateWindow, right: RateWindow) -> bool:
    return (
        left.window_seconds == right.window_seconds
        and left.used_percent == right.used_percent
        and left.reset_at == right.reset_at
    )


def _parse_window_lenient(raw: Any) -> RateWindow | None:
    try:
        return _parse_window(raw)
    except WindowShapeError:
        return None


def _parse_window(raw: Any) -> RateWindow | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise WindowShapeError("window is not an object")

    used_percent = raw.get("used_percent")
    if isinstance(used_percent, bool) or not isinstance(used_percent, (int, float)):
        raise WindowShapeError("window.used_percent is missing or invalid")

    limit_seconds = raw.get("limit_window_seconds")
    window_seconds = _window_seconds(limit_seconds)
    window_minutes = _window_minutes(limit_seconds)
    used = float(used_percent)
    if not math.isfinite(used) or not 0.0 <= used <= 100.0:
        raise WindowShapeError("window.used_percent is outside 0..100")
    return RateWindow(
        used_percent=used,
        remaining_percent=max(0.0, 100.0 - used),
        reset_at=parse_unix_timestamp(raw.get("reset_at")),
        window_minutes=window_minutes,
        window_seconds=window_seconds,
    )


def _window_seconds(value: Any) -> int | None:
    if not isinstance(value, (int, float)):
        return None
    if value <= 0:
        return None
    return int(value)


def _window_minutes(value: Any) -> int | None:
    if not isinstance(value, (int, float)):
        return None
    if value <= 0:
        return None
    return int(value / 60)
