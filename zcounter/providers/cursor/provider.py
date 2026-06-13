from __future__ import annotations

from typing import Any

from zcounter.models import QuotaSnapshot, RateWindow, parse_iso_datetime, utc_now
from zcounter.providers.cursor.config import CursorConfigError, load_cursor_config
from zcounter.providers.cursor.usage_api import (
    CursorAPIError,
    CursorShapeError,
    fetch_auth_me,
    fetch_usage_summary,
)


class CursorUsageShapeError(Exception):
    pass


CURSOR_AUTO_LABEL = "Auto(+Composer)"
CURSOR_API_LABEL = "API"


def fetch_cursor_quota_if_configured() -> QuotaSnapshot | None:
    try:
        config = load_cursor_config()
    except CursorConfigError as exc:
        return _error_snapshot(str(exc))

    if config is None or not config.enabled or not config.cookie_header:
        return None

    try:
        usage_summary = fetch_usage_summary(config.cookie_header)
    except CursorAPIError as exc:
        return _error_snapshot(str(exc), warnings=config.warnings)

    user_info: dict[str, Any] | None
    try:
        user_info = fetch_auth_me(config.cookie_header)
    except CursorAPIError:
        user_info = None

    try:
        return normalize_cursor_snapshot(usage_summary, user_info, warnings=config.warnings)
    except (CursorUsageShapeError, CursorShapeError) as exc:
        return _error_snapshot(str(exc), warnings=config.warnings)
    except Exception:
        return _error_snapshot("unexpected cursor fetch error", warnings=config.warnings)


def normalize_cursor_snapshot(
    usage_summary: dict[str, Any],
    user_info: dict[str, Any] | None,
    warnings: tuple[str, ...] = (),
) -> QuotaSnapshot:
    primary = _primary_window(usage_summary)
    if primary is None:
        raise CursorUsageShapeError("cursor usage summary contains no usable quota")

    secondary = _auto_window(usage_summary)
    tertiary = _api_window(usage_summary)
    email = _string(user_info.get("email")) if isinstance(user_info, dict) else None
    provider_account_id = _string(user_info.get("sub")) if isinstance(user_info, dict) else None
    return QuotaSnapshot(
        provider="cursor",
        email=email,
        plan=_cursor_plan_label(_string(usage_summary.get("membershipType"))),
        chatgpt_account_id=None,
        five_hour=None,
        weekly=None,
        primary=primary,
        secondary=secondary,
        tertiary=tertiary,
        primary_label="Total",
        secondary_label=CURSOR_AUTO_LABEL,
        tertiary_label=CURSOR_API_LABEL if tertiary is not None else None,
        provider_account_id=provider_account_id,
        source="cursor-usage-summary",
        updated_at=utc_now(),
        error=None,
        warnings=warnings,
        details=_details(usage_summary),
    )


def _primary_window(data: dict[str, Any]) -> RateWindow | None:
    reset_at = parse_iso_datetime(data.get("billingCycleEnd"))
    plan = _dict_path(data, "individualUsage", "plan")
    auto_percent = _display_percent(plan.get("autoPercentUsed")) if plan else None
    api_percent = _display_percent(plan.get("apiPercentUsed")) if plan else None

    if plan:
        total_percent = _display_percent(plan.get("totalPercentUsed"))
        if total_percent is not None:
            return _window(total_percent, reset_at)
        if auto_percent is not None and api_percent is not None:
            return _window((auto_percent + api_percent) / 2, reset_at)
        if api_percent is not None:
            return _window(api_percent, reset_at)
        if auto_percent is not None:
            return _window(auto_percent, reset_at)
        ratio = _ratio_percent(plan.get("used"), plan.get("limit"))
        if ratio is not None:
            return _window(ratio, reset_at)

    overall = _dict_path(data, "individualUsage", "overall")
    if overall:
        ratio = _ratio_percent(overall.get("used"), overall.get("limit"))
        if ratio is not None:
            return _window(ratio, reset_at)

    pooled = _dict_path(data, "teamUsage", "pooled")
    if pooled:
        ratio = _ratio_percent(pooled.get("used"), pooled.get("limit"))
        if ratio is not None:
            return _window(ratio, reset_at)

    return None


def _auto_window(data: dict[str, Any]) -> RateWindow | None:
    plan = _dict_path(data, "individualUsage", "plan")
    if not plan:
        return None
    percent = _display_percent(plan.get("autoPercentUsed"))
    if percent is None:
        return None
    return _window(percent, parse_iso_datetime(data.get("billingCycleEnd")))


def _api_window(data: dict[str, Any]) -> RateWindow | None:
    plan = _dict_path(data, "individualUsage", "plan")
    if not plan:
        return None
    percent = _display_percent(plan.get("apiPercentUsed"))
    if percent is None:
        return None
    return _window(percent, parse_iso_datetime(data.get("billingCycleEnd")))


def _details(data: dict[str, Any]) -> dict[str, Any]:
    plan = _dict_path(data, "individualUsage", "plan")
    on_demand = _dict_path(data, "individualUsage", "onDemand")
    team_on_demand = _dict_path(data, "teamUsage", "onDemand")
    details: dict[str, Any] = {
        "billing_cycle_start": _string(data.get("billingCycleStart")),
        "billing_cycle_end": _string(data.get("billingCycleEnd")),
        "membership_type": _string(data.get("membershipType")),
        "limit_type": _string(data.get("limitType")),
        "is_unlimited": data.get("isUnlimited") if isinstance(data.get("isUnlimited"), bool) else None,
    }
    if plan:
        details["api_used_percent"] = _display_percent(plan.get("apiPercentUsed"))
    if on_demand:
        details["on_demand_used_cents"] = _int_value(on_demand.get("used"))
        details["on_demand_limit_cents"] = _int_value(on_demand.get("limit"))
        details["on_demand_remaining_cents"] = _int_value(on_demand.get("remaining"))
    if team_on_demand:
        details["team_on_demand_used_cents"] = _int_value(team_on_demand.get("used"))
        details["team_on_demand_limit_cents"] = _int_value(team_on_demand.get("limit"))
        details["team_on_demand_remaining_cents"] = _int_value(team_on_demand.get("remaining"))
    return {key: value for key, value in details.items() if value is not None}


def _window(used_percent: float, reset_at) -> RateWindow:
    used = max(0.0, min(100.0, used_percent))
    return RateWindow(
        used_percent=used,
        remaining_percent=max(0.0, 100.0 - used),
        reset_at=reset_at,
        window_minutes=None,
    )


def _dict_path(data: dict[str, Any], *keys: str) -> dict[str, Any] | None:
    value: Any = data
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value if isinstance(value, dict) else None


def _display_percent(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    percent = float(value)
    if percent <= 0:
        return 0.0
    if percent > 100:
        return 100.0
    return percent


def _ratio_percent(used: Any, limit: Any) -> float | None:
    if not isinstance(used, (int, float)) or not isinstance(limit, (int, float)):
        return None
    if limit <= 0:
        return None
    return max(0.0, min(100.0, (float(used) / float(limit)) * 100.0))


def _string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _cursor_plan_label(value: str | None) -> str | None:
    if value is None:
        return None
    return f"Cursor {value[:1].upper()}{value[1:]}"


def _error_snapshot(message: str, warnings: tuple[str, ...] = ()) -> QuotaSnapshot:
    return QuotaSnapshot(
        provider="cursor",
        email=None,
        plan=None,
        chatgpt_account_id=None,
        five_hour=None,
        weekly=None,
        primary=None,
        secondary=None,
        tertiary=None,
        primary_label="Total",
        secondary_label=CURSOR_AUTO_LABEL,
        tertiary_label=None,
        provider_account_id=None,
        source="cursor-usage-summary",
        updated_at=utc_now(),
        error=message,
        warnings=warnings,
    )
