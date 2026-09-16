from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10.0
WEBHOOK_URL_ENV = "DISCORD_WEBHOOK_URL"
USER_AGENT = "zCounter/0.2"
_ERROR_BODY_MAX_CHARS = 500
_WEBHOOK_URL_RE = re.compile(r"https://discord\.com/api/webhooks/\S+")
_WEBHOOK_PATH_RE = re.compile(r"/api/webhooks/\d+/\S+")


def resolve_webhook_url(explicit: str | None = None) -> str | None:
    value = (explicit if explicit is not None else os.environ.get(WEBHOOK_URL_ENV, "")).strip()
    return value or None


def _safe_error_body(raw: bytes | None) -> str:
    if not raw:
        return ""
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    text = _WEBHOOK_URL_RE.sub("[redacted]", text)
    text = _WEBHOOK_PATH_RE.sub("[redacted]", text)
    if len(text) > _ERROR_BODY_MAX_CHARS:
        return f"{text[:_ERROR_BODY_MAX_CHARS]}...(truncated)"
    return text


def _log_http_failure(status: int, body: bytes | None = None) -> None:
    detail = _safe_error_body(body)
    if detail:
        logger.warning("discord notify failed: HTTP %s: %s", status, detail)
        return
    logger.warning("discord notify failed: HTTP %s", status)


def send_discord_message(
    content: str,
    *,
    webhook_url: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    url = resolve_webhook_url(webhook_url)
    if not url:
        return False

    payload = json.dumps(
        {
            "content": content,
            "allowed_mentions": {"parse": []},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if 200 <= response.status < 300:
                return True
            _log_http_failure(response.status, response.read())
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except OSError:
            body = None
        _log_http_failure(exc.code, body)
    except TimeoutError:
        logger.warning("discord notify failed: timeout")
    except urllib.error.URLError:
        logger.warning("discord notify failed: network error")
    except OSError:
        logger.warning("discord notify failed: network error")
    return False
