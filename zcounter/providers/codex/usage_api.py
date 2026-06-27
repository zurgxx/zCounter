from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from zcounter.models import CodexResetCredits, RateWindow, parse_iso_datetime, parse_unix_timestamp, utc_now


USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
RESET_CREDITS_URL = "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits"


class UsageAPIError(Exception):
    pass


class UnauthorizedError(UsageAPIError):
    pass


class UsageShapeError(UsageAPIError):
    pass


class WindowShapeError(Exception):
    pass


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


def normalize_usage_response(data: dict[str, Any]) -> tuple[RateWindow | None, RateWindow | None]:
    rate_limit = data.get("rate_limit")
    if not isinstance(rate_limit, dict):
        raise UsageShapeError("usage API response missing rate_limit object")
    five_hour = _parse_window_lenient(rate_limit.get("primary_window"))
    weekly = _parse_window_lenient(rate_limit.get("secondary_window"))
    if five_hour is None and weekly is None:
        raise UsageShapeError("usage API response contains no rate limit windows")
    return five_hour, weekly


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
    if not isinstance(used_percent, (int, float)):
        raise WindowShapeError("window.used_percent is missing or invalid")

    limit_seconds = raw.get("limit_window_seconds")
    window_minutes = _window_minutes(limit_seconds)
    used = max(0.0, min(100.0, float(used_percent)))
    return RateWindow(
        used_percent=used,
        remaining_percent=max(0.0, 100.0 - used),
        reset_at=parse_unix_timestamp(raw.get("reset_at")),
        window_minutes=window_minutes,
    )


def _window_minutes(value: Any) -> int | None:
    if not isinstance(value, (int, float)):
        return None
    if value <= 0:
        return None
    return int(value / 60)
