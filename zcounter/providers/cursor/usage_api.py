from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


AUTH_ME_URL = "https://cursor.com/api/auth/me"
USAGE_SUMMARY_URL = "https://cursor.com/api/usage-summary"
USER_AGENT = "zCounter/0.2"


class CursorAPIError(Exception):
    pass


class CursorUnauthorizedError(CursorAPIError):
    pass


class CursorShapeError(CursorAPIError):
    pass


def fetch_auth_me(cookie_header: str, timeout_seconds: float = 20.0) -> dict[str, Any]:
    return _fetch_json(AUTH_ME_URL, cookie_header, timeout_seconds)


def fetch_usage_summary(cookie_header: str, timeout_seconds: float = 20.0) -> dict[str, Any]:
    return _fetch_json(USAGE_SUMMARY_URL, cookie_header, timeout_seconds)


def _fetch_json(url: str, cookie_header: str, timeout_seconds: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "Cookie": cookie_header,
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise CursorUnauthorizedError("cursor session is invalid or expired") from exc
        raise CursorAPIError(f"cursor API returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise CursorAPIError("cursor API request failed") from exc
    except TimeoutError as exc:
        raise CursorAPIError("cursor API request timed out") from exc

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CursorShapeError("cursor API response is not valid JSON") from exc
    if not isinstance(data, dict):
        raise CursorShapeError("cursor API response root is not an object")
    return data
