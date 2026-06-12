from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


CACHE_ENV = "ZCOUNTER_CLAUDE_PROFILE_CACHE"


@dataclass(frozen=True)
class ClaudeProfileCache:
    email: str | None
    provider_account_id: str | None


def cache_path() -> Path:
    override = os.environ.get(CACHE_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".zcounter" / "claude-profile-cache.json"


def load_profile_cache() -> ClaudeProfileCache:
    path = cache_path()
    if not path.is_file():
        return ClaudeProfileCache(email=None, provider_account_id=None)
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return ClaudeProfileCache(email=None, provider_account_id=None)
    if not isinstance(data, dict):
        return ClaudeProfileCache(email=None, provider_account_id=None)
    return ClaudeProfileCache(
        email=_string(data.get("email")),
        provider_account_id=_string(data.get("provider_account_id")),
    )


def save_profile_cache(email: str | None, provider_account_id: str | None) -> None:
    if not email and not provider_account_id:
        return
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "email": email,
        "provider_account_id": provider_account_id,
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def _string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
