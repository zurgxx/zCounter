from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_unix_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def isoformat_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RateWindow:
    used_percent: float
    remaining_percent: float
    reset_at: datetime | None
    window_minutes: int | None

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["reset_at"] = isoformat_or_none(self.reset_at)
        return data


@dataclass(frozen=True)
class CodexResetCredits:
    available_count: int
    expires_at: tuple[datetime, ...]


@dataclass(frozen=True)
class CodexAccount:
    account_key: str
    chatgpt_account_id: str | None
    email: str | None
    plan: str | None
    active: bool = False


@dataclass(frozen=True)
class QuotaSnapshot:
    provider: str
    email: str | None
    plan: str | None
    chatgpt_account_id: str | None
    five_hour: RateWindow | None
    weekly: RateWindow | None
    source: str
    updated_at: datetime
    error: str | None = None
    primary: RateWindow | None = None
    secondary: RateWindow | None = None
    tertiary: RateWindow | None = None
    primary_label: str | None = None
    secondary_label: str | None = None
    tertiary_label: str | None = None
    provider_account_id: str | None = None
    warnings: tuple[str, ...] = ()
    details: dict[str, Any] | None = None
    codex_reset_credits: CodexResetCredits | None = None

    def to_json(self) -> dict[str, Any]:
        primary = self.primary or self.five_hour
        secondary = self.secondary or self.weekly
        tertiary = self.tertiary
        return {
            "provider": self.provider,
            "email": self.email,
            "plan": self.plan,
            "chatgpt_account_id": self.chatgpt_account_id,
            "provider_account_id": self.provider_account_id,
            "five_hour": self.five_hour.to_json() if self.five_hour else None,
            "weekly": self.weekly.to_json() if self.weekly else None,
            "primary": primary.to_json() if primary else None,
            "secondary": secondary.to_json() if secondary else None,
            "tertiary": tertiary.to_json() if tertiary else None,
            "primary_label": self.primary_label,
            "secondary_label": self.secondary_label,
            "tertiary_label": self.tertiary_label,
            "source": self.source,
            "updated_at": isoformat_or_none(self.updated_at),
            "error": self.error,
            "warnings": list(self.warnings),
            "details": self.details or {},
        }
