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

    def to_json(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "email": self.email,
            "plan": self.plan,
            "chatgpt_account_id": self.chatgpt_account_id,
            "five_hour": self.five_hour.to_json() if self.five_hour else None,
            "weekly": self.weekly.to_json() if self.weekly else None,
            "source": self.source,
            "updated_at": isoformat_or_none(self.updated_at),
            "error": self.error,
        }

