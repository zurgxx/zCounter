from __future__ import annotations

from typing import Any

from zcounter.models import QuotaSnapshot, RateWindow, parse_iso_datetime, utc_now
from zcounter.providers.claude.auth import ClaudeAuth, ClaudeAuthError, load_claude_auth
from zcounter.providers.claude.usage_api import (
    ClaudeAPIError,
    ClaudeShapeError,
    ClaudeUnauthorizedError,
    fetch_profile,
    fetch_usage,
)


class ClaudeUsageShapeError(Exception):
    pass


def fetch_claude_quota() -> QuotaSnapshot:
    try:
        auth = load_claude_auth()
    except ClaudeAuthError as exc:
        return _error_snapshot(str(exc))

    if not auth.access_token:
        return _error_snapshot("claude credentials have no access token")

    try:
        usage = fetch_usage(auth.access_token)
    except ClaudeAPIError as exc:
        return _error_snapshot(str(exc))

    profile: dict[str, Any] | None
    try:
        profile = fetch_profile(auth.access_token)
    except ClaudeAPIError:
        profile = None

    try:
        return normalize_claude_snapshot(usage, profile, auth)
    except ClaudeUsageShapeError as exc:
        return _error_snapshot(str(exc))
    except Exception:
        return _error_snapshot("unexpected claude fetch error")


def normalize_claude_snapshot(
    usage: dict[str, Any],
    profile: dict[str, Any] | None,
    auth: ClaudeAuth,
) -> QuotaSnapshot:
    primary = _window(usage.get("five_hour"), window_minutes=300)
    secondary = _window(usage.get("seven_day"), window_minutes=10_080)
    if primary is None and secondary is None:
        raise ClaudeUsageShapeError("claude usage response contains no usable quota")

    email = _profile_email(profile)
    provider_account_id = _profile_account_id(profile)
    return QuotaSnapshot(
        provider="claude",
        email=email,
        plan=_claude_plan_label(profile, auth),
        chatgpt_account_id=None,
        five_hour=primary,
        weekly=secondary,
        primary=primary,
        secondary=secondary,
        primary_label="5H",
        secondary_label="WK",
        provider_account_id=provider_account_id,
        source="claude-usage",
        updated_at=utc_now(),
        error=None,
        details=_details(usage, auth),
    )


def _window(raw: Any, window_minutes: int | None) -> RateWindow | None:
    if not isinstance(raw, dict):
        return None
    used_percent = _utilization_percent(raw.get("utilization"))
    if used_percent is None:
        return None
    return RateWindow(
        used_percent=used_percent,
        remaining_percent=max(0.0, 100.0 - used_percent),
        reset_at=parse_iso_datetime(raw.get("resets_at")),
        window_minutes=window_minutes,
    )


def _utilization_percent(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    raw = float(value)
    if raw < 0:
        return 0.0
    # Anthropic returns either a 0-1 fraction or a 0-100 percentage.
    percent = raw * 100.0 if raw <= 1.0 else raw
    return max(0.0, min(100.0, percent))


def _profile_email(profile: dict[str, Any] | None) -> str | None:
    if not isinstance(profile, dict):
        return None
    account = profile.get("account")
    if isinstance(account, dict):
        return _string(account.get("email"))
    return None


def _profile_account_id(profile: dict[str, Any] | None) -> str | None:
    if not isinstance(profile, dict):
        return None
    account = profile.get("account")
    if isinstance(account, dict):
        return _string(account.get("uuid"))
    return None


def _claude_plan_label(profile: dict[str, Any] | None, auth: ClaudeAuth) -> str | None:
    if isinstance(profile, dict):
        account = profile.get("account")
        if isinstance(account, dict):
            if account.get("has_claude_max") is True:
                return "Max"
            if account.get("has_claude_pro") is True:
                return "Pro"
        organization = profile.get("organization")
        if isinstance(organization, dict):
            org_type = _string(organization.get("organization_type"))
            if org_type == "claude_max":
                return "Max"
            if org_type == "claude_pro":
                return "Pro"
            if org_type:
                return _title_plan(org_type.removeprefix("claude_"))

    if auth.subscription_type:
        return _title_plan(auth.subscription_type)
    return None


def _details(usage: dict[str, Any], auth: ClaudeAuth) -> dict[str, Any]:
    extra_usage = usage.get("extra_usage")
    details: dict[str, Any] = {
        "subscription_type": auth.subscription_type,
        "rate_limit_tier": auth.rate_limit_tier,
    }
    if isinstance(extra_usage, dict):
        if isinstance(extra_usage.get("is_enabled"), bool):
            details["extra_usage_enabled"] = extra_usage["is_enabled"]
        utilization = _utilization_percent(extra_usage.get("utilization"))
        if utilization is not None:
            details["extra_usage_utilization"] = utilization
    for key in (
        "seven_day_sonnet",
        "seven_day_opus",
        "seven_day_oauth_apps",
        "seven_day_cowork",
    ):
        window = usage.get(key)
        if isinstance(window, dict):
            percent = _utilization_percent(window.get("utilization"))
            if percent is not None:
                details[f"{key}_utilization"] = percent
    return {key: value for key, value in details.items() if value is not None}


def _title_plan(plan: str) -> str:
    return plan[:1].upper() + plan[1:]


def _string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _error_snapshot(message: str) -> QuotaSnapshot:
    return QuotaSnapshot(
        provider="claude",
        email=None,
        plan=None,
        chatgpt_account_id=None,
        five_hour=None,
        weekly=None,
        primary=None,
        secondary=None,
        primary_label="5H",
        secondary_label="WK",
        provider_account_id=None,
        source="claude-usage",
        updated_at=utc_now(),
        error=message,
    )
