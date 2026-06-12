from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from zcounter.providers.claude.rate_limit_gate import (
    blocked_until,
    parse_retry_after,
    record_rate_limit,
    record_success,
)


USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
PROFILE_URL = "https://api.anthropic.com/api/oauth/profile"
OAUTH_BETA = "oauth-2025-04-20"
FALLBACK_CLAUDE_CODE_VERSION = "2.1.0"
RATE_LIMIT_MESSAGE = (
    "Claude OAuth usage endpoint is rate limited by Anthropic right now. "
    "Wait a few minutes, then click Refresh."
)


class ClaudeAPIError(Exception):
    pass


class ClaudeUnauthorizedError(ClaudeAPIError):
    pass


class ClaudeRateLimitedError(ClaudeAPIError):
    pass


class ClaudeShapeError(ClaudeAPIError):
    pass


def fetch_usage(
    access_token: str,
    *,
    user_initiated: bool = False,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    return _fetch_json(
        USAGE_URL,
        access_token,
        user_initiated=user_initiated,
        timeout_seconds=timeout_seconds,
    )


def fetch_profile(
    access_token: str,
    *,
    user_initiated: bool = True,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    return _fetch_json(
        PROFILE_URL,
        access_token,
        user_initiated=user_initiated,
        timeout_seconds=timeout_seconds,
    )


def claude_code_user_agent() -> str:
    version = os.environ.get("ZCOUNTER_CLAUDE_CODE_VERSION", FALLBACK_CLAUDE_CODE_VERSION).strip()
    if not version:
        version = FALLBACK_CLAUDE_CODE_VERSION
    return f"claude-code/{version}"


def _fetch_json(
    url: str,
    access_token: str,
    *,
    user_initiated: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    if url == USAGE_URL:
        blocked = blocked_until(user_initiated=user_initiated)
        if blocked is not None:
            raise ClaudeRateLimitedError(RATE_LIMIT_MESSAGE)

    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "anthropic-beta": OAUTH_BETA,
            "User-Agent": claude_code_user_agent(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ClaudeUnauthorizedError("Claude Code login required or token expired") from exc
        if exc.code == 429:
            retry_after = parse_retry_after(exc.headers.get("Retry-After"))
            if url == USAGE_URL:
                record_rate_limit(retry_after)
            raise ClaudeRateLimitedError(RATE_LIMIT_MESSAGE) from exc
        raise ClaudeAPIError(f"claude API returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ClaudeAPIError("claude API request failed") from exc
    except TimeoutError as exc:
        raise ClaudeAPIError("claude API request timed out") from exc

    if url == USAGE_URL:
        record_success()

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClaudeShapeError("claude API response is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ClaudeShapeError("claude API response root is not an object")
    return data
