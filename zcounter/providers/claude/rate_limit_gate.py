from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path


DEFAULT_COOLDOWN_SECONDS = 60 * 5
STATE_ENV = "ZCOUNTER_CLAUDE_RATE_LIMIT_STATE"


def _state_path() -> Path:
    override = os.environ.get(STATE_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".zcounter" / "claude-oauth-rate-limit.json"


def blocked_until(*, user_initiated: bool = False, now: datetime | None = None) -> datetime | None:
    if user_initiated:
        return None
    return current_blocked_until(now=now)


def current_blocked_until(now: datetime | None = None) -> datetime | None:
    current = _ensure_aware(now or datetime.now(timezone.utc))
    raw = _read_state().get("blocked_until")
    if not isinstance(raw, str):
        return None
    blocked = _parse_iso(raw)
    if blocked is None or blocked <= current:
        clear()
        return None
    return blocked


def record_rate_limit(retry_after: datetime | None = None, now: datetime | None = None) -> None:
    current = _ensure_aware(now or datetime.now(timezone.utc))
    if retry_after is not None:
        blocked = _ensure_aware(retry_after)
        if blocked <= current:
            blocked = current + timedelta(seconds=DEFAULT_COOLDOWN_SECONDS)
    else:
        blocked = current + timedelta(seconds=DEFAULT_COOLDOWN_SECONDS)
    _write_state({"blocked_until": blocked.isoformat()})


def record_success() -> None:
    clear()


def clear() -> None:
    path = _state_path()
    if path.exists():
        path.unlink()


def parse_retry_after(header_value: str | None, now: datetime | None = None) -> datetime | None:
    if not header_value:
        return None
    raw = header_value.strip()
    if not raw:
        return None
    current = _ensure_aware(now or datetime.now(timezone.utc))
    try:
        seconds = float(raw)
    except ValueError:
        seconds = None
    if seconds is not None and seconds >= 0:
        return current + timedelta(seconds=seconds)
    try:
        return _ensure_aware(parsedate_to_datetime(raw))
    except (TypeError, ValueError, OverflowError):
        return None


def _read_state() -> dict[str, object]:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(payload: dict[str, object]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _ensure_aware(parsed)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
