from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
PROFILE_URL = "https://api.anthropic.com/api/oauth/profile"
OAUTH_BETA = "oauth-2025-04-20"
USER_AGENT = "zCounter/0.3"


class ClaudeAPIError(Exception):
    pass


class ClaudeUnauthorizedError(ClaudeAPIError):
    pass


class ClaudeShapeError(ClaudeAPIError):
    pass


def fetch_usage(access_token: str, timeout_seconds: float = 20.0) -> dict[str, Any]:
    return _fetch_json(USAGE_URL, access_token, timeout_seconds)


def fetch_profile(access_token: str, timeout_seconds: float = 20.0) -> dict[str, Any]:
    return _fetch_json(PROFILE_URL, access_token, timeout_seconds)


def _fetch_json(url: str, access_token: str, timeout_seconds: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "anthropic-beta": OAUTH_BETA,
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ClaudeUnauthorizedError("Claude Code login required or token expired") from exc
        raise ClaudeAPIError(f"claude API returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ClaudeAPIError("claude API request failed") from exc
    except TimeoutError as exc:
        raise ClaudeAPIError("claude API request timed out") from exc

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClaudeShapeError("claude API response is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ClaudeShapeError("claude API response root is not an object")
    return data
