from __future__ import annotations

from pathlib import Path

from zcounter.models import QuotaSnapshot, utc_now
from zcounter.providers.codex.auth import load_auth_files, match_auth_by_account_id
from zcounter.providers.codex.registry import RegistryError, list_accounts
from zcounter.providers.codex.usage_api import (
    UsageAPIError,
    UsageShapeError,
    fetch_usage,
    normalize_usage_response,
)


def fetch_codex_quotas(registry_file: Path | None = None) -> list[QuotaSnapshot]:
    try:
        accounts = list_accounts(registry_file)
    except RegistryError as exc:
        return [
            QuotaSnapshot(
                provider="codex",
                email=None,
                plan=None,
                chatgpt_account_id=None,
                five_hour=None,
                weekly=None,
                source="codex-auth-registry",
                updated_at=utc_now(),
                error=str(exc),
                primary_label="5H",
                secondary_label="WEEK",
            )
        ]

    auths_by_account_id = match_auth_by_account_id(load_auth_files())
    snapshots: list[QuotaSnapshot] = []
    for account in accounts:
        snapshots.append(_fetch_account_quota(account, auths_by_account_id))
    return snapshots


def _fetch_account_quota(account, auths_by_account_id) -> QuotaSnapshot:
    now = utc_now()
    account_id = account.chatgpt_account_id
    if not account_id:
        return _error_snapshot(account, "registry account is missing chatgpt_account_id", now)

    auth = auths_by_account_id.get(account_id)
    if auth is None:
        return _error_snapshot(account, "matching auth file was not found", now)
    if not auth.access_token:
        return _error_snapshot(account, "matching auth file has no access token", now)

    try:
        response = fetch_usage(auth.access_token, account_id)
        five_hour, weekly = normalize_usage_response(response)
        plan = account.plan or _string_plan(response.get("plan_type"))
        return QuotaSnapshot(
            provider="codex",
            email=account.email or auth.email,
            plan=plan,
            chatgpt_account_id=account_id,
            five_hour=five_hour,
            weekly=weekly,
            source="wham-usage",
            updated_at=utc_now(),
            error=None,
            primary=five_hour,
            secondary=weekly,
            primary_label="5H",
            secondary_label="WEEK",
            provider_account_id=account_id,
        )
    except (UsageAPIError, UsageShapeError) as exc:
        return _error_snapshot(account, str(exc), utc_now())
    except Exception:
        return _error_snapshot(account, "unexpected account fetch error", utc_now())


def _error_snapshot(account, message: str, updated_at) -> QuotaSnapshot:
    return QuotaSnapshot(
        provider="codex",
        email=account.email,
        plan=account.plan,
        chatgpt_account_id=account.chatgpt_account_id,
        five_hour=None,
        weekly=None,
        source="wham-usage",
        updated_at=updated_at,
        error=message,
        primary_label="5H",
        secondary_label="WEEK",
        provider_account_id=account.chatgpt_account_id,
    )


def _string_plan(value) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None
