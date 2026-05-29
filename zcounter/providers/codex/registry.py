from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from zcounter.models import CodexAccount


class RegistryError(Exception):
    pass


def codex_home() -> Path:
    raw = os.environ.get("CODEX_HOME")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".codex"


def registry_path() -> Path:
    return codex_home() / "accounts" / "registry.json"


def load_registry(path: Path | None = None) -> dict[str, Any]:
    target = path or registry_path()
    if not target.exists():
        raise RegistryError(f"registry not found: {target}")
    try:
        with target.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise RegistryError(f"registry could not be read: {target}") from exc
    except json.JSONDecodeError as exc:
        raise RegistryError(f"registry is not valid JSON: {target}") from exc
    if not isinstance(data, dict):
        raise RegistryError(f"registry root is not an object: {target}")
    return data


def list_accounts(path: Path | None = None) -> list[CodexAccount]:
    data = load_registry(path)
    raw_accounts = data.get("accounts")
    if not isinstance(raw_accounts, list):
        raise RegistryError("registry accounts[] is missing or invalid")

    active_key = data.get("active_account_key")
    accounts: list[CodexAccount] = []
    for raw in raw_accounts:
        if not isinstance(raw, dict):
            continue
        account_key = _string_or_none(raw.get("account_key")) or ""
        chatgpt_account_id = _string_or_none(raw.get("chatgpt_account_id"))
        accounts.append(
            CodexAccount(
                account_key=account_key,
                chatgpt_account_id=chatgpt_account_id,
                email=_string_or_none(raw.get("email")),
                plan=_string_or_none(raw.get("plan")),
                active=bool(account_key and account_key == active_key),
            )
        )
    return accounts


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None
