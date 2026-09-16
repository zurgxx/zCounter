from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10.0
WEBHOOK_URL_ENV = "DISCORD_WEBHOOK_URL"


def resolve_webhook_url(explicit: str | None = None) -> str | None:
    value = (explicit if explicit is not None else os.environ.get(WEBHOOK_URL_ENV, "")).strip()
    return value or None


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
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if 200 <= response.status < 300:
                return True
            logger.warning("discord notify failed: HTTP %s", response.status)
    except urllib.error.HTTPError as exc:
        logger.warning("discord notify failed: HTTP %s", exc.code)
    except TimeoutError:
        logger.warning("discord notify failed: timeout")
    except urllib.error.URLError:
        logger.warning("discord notify failed: network error")
    except OSError:
        logger.warning("discord notify failed: network error")
    return False
