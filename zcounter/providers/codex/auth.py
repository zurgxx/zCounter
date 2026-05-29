from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zcounter.providers.codex.registry import codex_home


@dataclass(frozen=True)
class CodexAuth:
    path: Path
    account_id: str | None
    access_token: str | None
    refresh_token: str | None
    id_token: str | None
    email: str | None


def accounts_dir() -> Path:
    return codex_home() / "accounts"


def load_auth_files(directory: Path | None = None) -> list[CodexAuth]:
    root = directory or accounts_dir()
    if not root.exists():
        return []
    auths: list[CodexAuth] = []
    for path in sorted(root.glob("*.auth.json")):
        auth = load_auth_file(path)
        if auth is not None:
            auths.append(auth)
    return auths


def load_auth_file(path: Path) -> CodexAuth | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        tokens = {}

    id_token = _string_or_none(tokens.get("id_token")) or _string_or_none(tokens.get("idToken"))
    payload = decode_jwt_payload(id_token) if id_token else {}
    auth_payload = payload.get("https://api.openai.com/auth")
    if not isinstance(auth_payload, dict):
        auth_payload = {}
    profile_payload = payload.get("https://api.openai.com/profile")
    if not isinstance(profile_payload, dict):
        profile_payload = {}

    account_id = (
        _string_or_none(tokens.get("account_id"))
        or _string_or_none(tokens.get("accountId"))
        or _string_or_none(auth_payload.get("chatgpt_account_id"))
        or _string_or_none(payload.get("chatgpt_account_id"))
    )
    email = (
        _string_or_none(payload.get("email"))
        or _string_or_none(profile_payload.get("email"))
    )

    return CodexAuth(
        path=path,
        account_id=account_id,
        access_token=_string_or_none(tokens.get("access_token"))
        or _string_or_none(tokens.get("accessToken")),
        refresh_token=_string_or_none(tokens.get("refresh_token"))
        or _string_or_none(tokens.get("refreshToken")),
        id_token=id_token,
        email=email,
    )


def match_auth_by_account_id(auths: list[CodexAuth]) -> dict[str, CodexAuth]:
    result: dict[str, CodexAuth] = {}
    for auth in auths:
        if auth.account_id and auth.account_id not in result:
            result[auth.account_id] = auth
    return result


def decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload + padding)
        value = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None

