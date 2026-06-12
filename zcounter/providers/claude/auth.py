from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ENV_CLAUDE_CONFIG_DIR = "CLAUDE_CONFIG_DIR"
CREDENTIALS_FILENAME = ".credentials.json"


class ClaudeAuthError(Exception):
    pass


@dataclass(frozen=True)
class ClaudeAuth:
    path: Path
    access_token: str | None
    subscription_type: str | None
    rate_limit_tier: str | None


def claude_home() -> Path:
    override = os.environ.get(ENV_CLAUDE_CONFIG_DIR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude"


def credentials_path() -> Path:
    return claude_home() / CREDENTIALS_FILENAME


def load_claude_auth() -> ClaudeAuth:
    path = credentials_path()
    if not path.exists():
        raise ClaudeAuthError("claude credentials were not found")
    if not path.is_file():
        raise ClaudeAuthError("claude credentials path is not a file")

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ClaudeAuthError("claude credentials are not valid JSON") from exc
    except OSError as exc:
        raise ClaudeAuthError("claude credentials could not be read") from exc

    if not isinstance(data, dict):
        raise ClaudeAuthError("claude credentials root is not an object")

    oauth = data.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        raise ClaudeAuthError("claude credentials are missing claudeAiOauth")

    return ClaudeAuth(
        path=path,
        access_token=_string_or_none(oauth.get("accessToken")),
        subscription_type=_string_or_none(oauth.get("subscriptionType")),
        rate_limit_tier=_string_or_none(oauth.get("rateLimitTier")),
    )


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None
