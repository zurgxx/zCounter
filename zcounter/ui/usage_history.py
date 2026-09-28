from __future__ import annotations

import json
import logging
import math
import os
import re
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from zcounter.models import (
    QuotaSnapshot,
    RateWindow,
    isoformat_or_none,
    parse_iso_datetime,
    utc_now,
)
from zcounter.ui.usage_log import usage_log_path


logger = logging.getLogger(__name__)

HISTORY_SCHEMA_VERSION = 1
USAGE_HISTORY_ENV = "ZCOUNTER_USAGE_HISTORY"
USAGE_HISTORY_FILENAME = "usage-history.jsonl"
GAP_THRESHOLD_SECONDS = 6 * 60
MAX_DRAW_POINTS_PER_CHART = 1800
# History currently uses only structured JSONL observations. Keep the legacy
# parser and an explicit switch so old logs can be included again if needed.
INCLUDE_LEGACY_USAGE_LOG = False
_TOKEN_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_LEGACY_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(.*)$")
_LEGACY_QUOTA_RE = re.compile(r"^([A-Za-z0-9_.-]+)=([+-]?(?:\d+(?:\.\d*)?|\.\d+))%$")

HISTORY_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("codex", "Codex"),
    ("claude", "Claude"),
    ("cursor", "Cursor"),
)
HISTORY_PERIODS: dict[str, timedelta | None] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "all": None,
}


@dataclass(frozen=True)
class QuotaValue:
    quota_id: str
    quota_label: str
    remaining_percent: float
    reset_at: datetime | None
    window_seconds: int | None = None
    window_minutes: int | None = None


@dataclass(frozen=True)
class HistoryObservation:
    recorded_at: datetime
    provider: str
    account_id: str
    display_name: str
    quota_id: str
    quota_label: str
    remaining_percent: float
    reset_at: datetime | None = None
    source: str = "jsonl"
    legacy_label: str | None = None
    window_seconds: int | None = None
    window_minutes: int | None = None


def usage_history_path() -> Path:
    override = os.environ.get(USAGE_HISTORY_ENV)
    if override:
        return Path(override).expanduser()

    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        return Path(xdg_state_home).expanduser() / "zcounter" / USAGE_HISTORY_FILENAME
    return Path.home() / ".local" / "state" / "zcounter" / USAGE_HISTORY_FILENAME


def append_usage_history(
    snapshots: Sequence[QuotaSnapshot],
    recorded_at: datetime,
    path: Path | None = None,
) -> bool:
    """成功したアカウント・quotaの観測を1行ずつJSONLへ追記する。"""
    labels = _legacy_labels(snapshots)
    lines: list[str] = []
    recorded_at_utc = _as_utc(recorded_at)

    for index, snapshot in enumerate(snapshots):
        if snapshot.error is not None:
            continue
        account_id = _stable_account_id(snapshot)
        # 表示名を推測で結合する系列は作成しない。
        if account_id is None:
            continue

        legacy_label = labels.get(index) if snapshot.provider != "claude" else None
        for quota in _quota_values(snapshot):
            observation = HistoryObservation(
                recorded_at=recorded_at_utc,
                provider=snapshot.provider,
                account_id=account_id,
                display_name=_display_name(snapshot),
                quota_id=quota.quota_id,
                quota_label=quota.quota_label,
                remaining_percent=quota.remaining_percent,
                reset_at=_as_utc(quota.reset_at) if quota.reset_at is not None else None,
                legacy_label=legacy_label,
                window_seconds=quota.window_seconds,
                window_minutes=quota.window_minutes,
            )
            lines.append(json.dumps(_observation_to_json(observation), ensure_ascii=False, allow_nan=False))

    if not lines:
        return False

    target = path or usage_history_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError:
        logger.warning("failed to append usage history", exc_info=True)
        return False
    return True


def read_usage_history(
    history_path: Path | None = None,
    legacy_path: Path | None = None,
) -> list[HistoryObservation]:
    """構造化JSONL履歴を読む。旧ログは明示的に有効化した場合のみ補う。"""
    structured = _read_jsonl(history_path or usage_history_path())
    legacy = (
        _read_legacy_log(legacy_path or usage_log_path())
        if INCLUDE_LEGACY_USAGE_LOG
        else []
    )

    aliases: dict[tuple[str, str], set[str]] = defaultdict(set)
    display_names: dict[tuple[str, str], tuple[datetime, str]] = {}
    structured_keys: dict[tuple[str, str, str], list[datetime]] = defaultdict(list)
    for observation in structured:
        if observation.legacy_label:
            aliases[(observation.provider, observation.legacy_label)].add(observation.account_id)
        display_key = (observation.provider, observation.account_id)
        current = display_names.get(display_key)
        if current is None or observation.recorded_at >= current[0]:
            display_names[display_key] = (observation.recorded_at, observation.display_name)
        if observation.legacy_label:
            structured_keys[
                (observation.provider, observation.legacy_label, observation.quota_id)
            ].append(observation.recorded_at)

    combined = list(structured)
    for observation in legacy:
        alias = observation.legacy_label or ""
        mapped_ids = aliases.get((observation.provider, alias), set())
        if len(mapped_ids) == 1:
            account_id = next(iter(mapped_ids))
            display_entry = display_names.get((observation.provider, account_id))
            display_name = display_entry[1] if display_entry else observation.display_name
            observation = replace(observation, account_id=account_id, display_name=display_name)

        # 両writerは同じrefreshで動くため、表示名・quota ID・秒単位時刻が
        # JSONLの観測と一致する旧ログ側の丸め値は重複として除外する。
        legacy_key = (
            observation.provider,
            alias,
            observation.quota_id,
        )
        if any(abs((at - observation.recorded_at).total_seconds()) < 1.1 for at in structured_keys.get(legacy_key, ())):
            continue
        combined.append(observation)

    return sorted(
        combined,
        key=lambda item: (
            item.provider,
            item.account_id,
            item.quota_id,
            item.recorded_at,
            item.source != "jsonl",
        ),
    )


def build_history_payload(
    observations: Sequence[HistoryObservation],
    provider: str = "codex",
    account_id: str | None = None,
    period: str = "24h",
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _as_utc(now or utc_now())
    valid_providers = {key for key, _ in HISTORY_PROVIDERS}
    selected_provider = provider if isinstance(provider, str) and provider in valid_providers else "codex"
    requested_period = period.lower() if isinstance(period, str) else ""
    selected_period = requested_period if requested_period in HISTORY_PERIODS else "24h"
    provider_observations = [item for item in observations if item.provider == selected_provider]

    names: dict[str, str] = {}
    latest_for_account: dict[str, datetime] = {}
    for item in provider_observations:
        if item.account_id not in latest_for_account or item.recorded_at >= latest_for_account[item.account_id]:
            latest_for_account[item.account_id] = item.recorded_at
            names[item.account_id] = item.display_name

    name_groups: dict[str, list[str]] = defaultdict(list)
    for account_key, display_name in names.items():
        name_groups[display_name.casefold()].append(account_key)
    accounts = []
    for key in sorted(names, key=lambda value: (names[value].casefold(), value)):
        label = names[key]
        duplicates = sorted(name_groups[label.casefold()])
        if len(duplicates) > 1:
            label = f"{label} ({duplicates.index(key) + 1})"
        accounts.append({"id": key, "label": label})
    account_ids = {item["id"] for item in accounts}
    selected_account = (
        account_id
        if isinstance(account_id, str) and account_id in account_ids
        else (accounts[0]["id"] if accounts else None)
    )
    account_observations = [
        item for item in provider_observations if item.account_id == selected_account
    ]

    duration = HISTORY_PERIODS[selected_period]
    if duration is None:
        visible_start = min((item.recorded_at for item in account_observations), default=current)
    else:
        visible_start = current - duration
    visible_end = current

    quota_groups: dict[str, list[HistoryObservation]] = defaultdict(list)
    for item in account_observations:
        quota_groups[item.quota_id].append(item)

    charts: list[dict[str, Any]] = []
    for quota_id, all_points in sorted(quota_groups.items(), key=lambda entry: _latest_quota_label(entry[1]).casefold()):
        all_points.sort(key=lambda item: item.recorded_at)
        visible_points = [
            item for item in all_points if visible_start <= item.recorded_at <= visible_end
        ]
        markers = sorted(
            {
                item.reset_at
                for item in all_points
                if item.source == "jsonl"
                and item.reset_at is not None
                and item.recorded_at <= item.reset_at
                and visible_start <= item.reset_at <= visible_end
            }
        )
        latest_structured = next(
            (item for item in reversed(all_points) if item.source == "jsonl"),
            None,
        )
        next_reset = (
            latest_structured.reset_at
            if latest_structured is not None
            and latest_structured.reset_at is not None
            and latest_structured.reset_at > current
            else None
        )

        raw_points = [
            {
                "timestamp": isoformat_or_none(item.recorded_at),
                "remaining_percent": item.remaining_percent,
                "source": item.source,
            }
            for item in visible_points
        ]
        segments, gaps = split_history_points(raw_points)
        protected = _reset_neighbor_timestamps(visible_points, markers)
        segments = _downsample_segments(segments, protected, MAX_DRAW_POINTS_PER_CHART)

        latest = latest_structured or all_points[-1]
        charts.append(
            {
                "quota_id": quota_id,
                "quota_label": latest.quota_label,
                "window_seconds": latest.window_seconds,
                "window_minutes": latest.window_minutes,
                "segments": segments,
                "gaps": gaps,
                "reset_markers": [isoformat_or_none(item) for item in markers],
                "next_reset": isoformat_or_none(next_reset),
            }
        )

    return {
        "provider": selected_provider,
        "period": selected_period,
        "accounts": accounts,
        "selected_account_id": selected_account,
        "range_start": isoformat_or_none(visible_start),
        "range_end": isoformat_or_none(visible_end),
        "charts": charts,
        "has_data": any(chart["segments"] for chart in charts),
    }


class UsageHistoryAPI:
    def __init__(
        self,
        history_path: Path | None = None,
        legacy_path: Path | None = None,
        now_fn: Callable[[], datetime] = utc_now,
    ) -> None:
        self._history_path = history_path
        self._legacy_path = legacy_path
        self._now_fn = now_fn

    def get_history(
        self,
        provider: str = "codex",
        account_id: str | None = None,
        period: str = "24h",
    ) -> dict[str, Any]:
        observations = read_usage_history(self._history_path, self._legacy_path)
        return build_history_payload(
            observations,
            provider=provider,
            account_id=account_id,
            period=period,
            now=self._now_fn(),
        )


def split_history_points(
    points: Sequence[dict[str, Any]],
    gap_threshold_seconds: int = GAP_THRESHOLD_SECONDS,
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]:
    if not points:
        return [], []

    ordered = sorted(points, key=lambda item: item["timestamp"])
    segments: list[list[dict[str, Any]]] = [[ordered[0]]]
    gaps: list[dict[str, Any]] = []
    previous_at = _parse_required_timestamp(ordered[0]["timestamp"])
    for point in ordered[1:]:
        point_at = _parse_required_timestamp(point["timestamp"])
        seconds = (point_at - previous_at).total_seconds()
        if seconds > gap_threshold_seconds:
            gaps.append(
                {
                    "from": isoformat_or_none(previous_at),
                    "to": isoformat_or_none(point_at),
                    "duration_seconds": seconds,
                }
            )
            segments.append([point])
        else:
            segments[-1].append(point)
        previous_at = point_at
    return segments, gaps


def _read_jsonl(path: Path) -> list[HistoryObservation]:
    observations: list[HistoryObservation] = []
    try:
        if not path.is_file():
            return []
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    observation = _parse_json_observation(raw)
                except (json.JSONDecodeError, TypeError, ValueError, OverflowError):
                    logger.debug("skipping invalid usage history row %s:%d", path, line_number)
                    continue
                if observation is not None:
                    observations.append(observation)
    except OSError:
        logger.warning("failed to read usage history %s", path, exc_info=True)
    return observations


def _parse_json_observation(raw: Any) -> HistoryObservation | None:
    schema_version = raw.get("schema_version") if isinstance(raw, dict) else None
    if (
        not isinstance(raw, dict)
        or isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != HISTORY_SCHEMA_VERSION
    ):
        return None
    recorded_at = parse_iso_datetime(raw.get("recorded_at"))
    reset_raw = raw.get("reset_at")
    reset_at = parse_iso_datetime(reset_raw) if reset_raw is not None else None
    if reset_raw is not None and reset_at is None:
        return None

    provider = _nonempty_string(raw.get("provider"))
    account_id = _nonempty_string(raw.get("account_id"))
    display_name = _nonempty_string(raw.get("display_name"))
    quota_id = _nonempty_string(raw.get("quota_id"))
    quota_label = _nonempty_string(raw.get("quota_label"))
    remaining = raw.get("remaining_percent")
    if (
        recorded_at is None
        or provider is None
        or account_id is None
        or display_name is None
        or quota_id is None
        or quota_label is None
        or isinstance(remaining, bool)
        or not isinstance(remaining, (int, float))
        or not math.isfinite(float(remaining))
        or not 0.0 <= float(remaining) <= 100.0
    ):
        return None

    return HistoryObservation(
        recorded_at=recorded_at,
        provider=provider,
        account_id=account_id,
        display_name=display_name,
        quota_id=quota_id,
        quota_label=quota_label,
        remaining_percent=float(remaining),
        reset_at=reset_at,
        source="jsonl",
        legacy_label=_nonempty_string(raw.get("legacy_label")),
        window_seconds=_optional_positive_int(raw.get("window_seconds")),
        window_minutes=_optional_positive_int(raw.get("window_minutes")),
    )


def _read_legacy_log(path: Path) -> list[HistoryObservation]:
    observations: list[HistoryObservation] = []
    try:
        if not path.is_file():
            return []
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, 1):
                match = _LEGACY_LINE_RE.match(line.rstrip("\r\n"))
                if match is None:
                    continue
                try:
                    local_at = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
                    recorded_at = local_at.astimezone(timezone.utc)
                except (ValueError, OverflowError):
                    continue

                for entry in match.group(2).split():
                    if ":" not in entry:
                        continue
                    account_label, quota_text = entry.split(":", 1)
                    values: list[tuple[str, float]] = []
                    for raw_value in quota_text.split(","):
                        value_match = _LEGACY_QUOTA_RE.fullmatch(raw_value)
                        if value_match is None:
                            continue
                        percent = float(value_match.group(2))
                        if not math.isfinite(percent) or not 0.0 <= percent <= 100.0:
                            continue
                        values.append((value_match.group(1), percent))
                    if not values:
                        continue

                    provider = _legacy_provider({key for key, _ in values})
                    if provider is None:
                        continue
                    for quota_id, percent in values:
                        observations.append(
                            HistoryObservation(
                                recorded_at=recorded_at,
                                provider=provider,
                                account_id=f"legacy:{provider}:{account_label}",
                                display_name=account_label,
                                quota_id=quota_id,
                                quota_label=_legacy_quota_label(quota_id),
                                remaining_percent=percent,
                                source="legacy",
                                legacy_label=account_label,
                            )
                        )
    except OSError:
        logger.warning("failed to read legacy usage log %s", path, exc_info=True)
    return observations


def _legacy_provider(quota_ids: set[str]) -> str | None:
    codex_ids = quota_ids.intersection({"five_hour", "weekly"})
    cursor_ids = quota_ids.intersection(
        {"total", "first_party_models", "api", "grok_bot_weekly"}
    )
    if codex_ids and cursor_ids:
        return None
    if cursor_ids:
        return "cursor"
    if codex_ids:
        return "codex"
    return None


def _legacy_quota_label(quota_id: str) -> str:
    known = {
        "five_hour": "Five Hour",
        "weekly": "Weekly",
        "total": "Total",
        "first_party_models": "First-party models",
        "api": "API",
        "grok_bot_weekly": "Grok Bot Weekly",
    }
    return known.get(quota_id, quota_id.replace("_", " ").title())


def _quota_values(snapshot: QuotaSnapshot) -> list[QuotaValue]:
    values: list[QuotaValue] = []
    seen_window_ids: set[int] = set()
    seen_durations: set[tuple[int | None, int | None]] = set()
    used_ids: set[str] = set()

    fixed_windows = (
        ("five_hour", snapshot.five_hour, "Five Hour"),
        ("weekly", snapshot.weekly, "Weekly"),
    )
    for quota_id, window, label in fixed_windows:
        if window is None:
            continue
        remaining = _remaining_percent(window)
        if remaining is None:
            continue
        values.append(_quota_value(quota_id, label, window, remaining))
        used_ids.add(quota_id)
        seen_window_ids.add(id(window))
        duration = _duration_key(window)
        if duration is not None:
            seen_durations.add(duration)

    generic_windows = (
        ("primary", snapshot.primary, snapshot.primary_label),
        ("secondary", snapshot.secondary, snapshot.secondary_label),
        ("tertiary", snapshot.tertiary, snapshot.tertiary_label),
    )
    for fallback, window, label in generic_windows:
        if window is None or id(window) in seen_window_ids:
            continue
        duration = _duration_key(window)
        if duration is not None and duration in seen_durations:
            continue
        remaining = _remaining_percent(window)
        if remaining is None:
            continue
        display_label = label.strip() if isinstance(label, str) and label.strip() else fallback.title()
        quota_id = _quota_token(display_label) or fallback
        if quota_id in used_ids:
            suffix = f"_{window.window_seconds}s" if window.window_seconds else f"_{window.window_minutes}m" if window.window_minutes else f"_{fallback}"
            quota_id = f"{quota_id}{suffix}"
        values.append(_quota_value(quota_id, display_label, window, remaining))
        used_ids.add(quota_id)
        seen_window_ids.add(id(window))
        if duration is not None:
            seen_durations.add(duration)

    grok = (
        snapshot.details.get("grok_bot")
        if snapshot.provider == "cursor" and isinstance(snapshot.details, dict)
        else None
    )
    if isinstance(grok, dict):
        remaining = _finite_percent(grok.get("remaining_percent"))
        if remaining is not None:
            label = _nonempty_string(grok.get("label")) or "Grok Bot"
            period = _nonempty_string(grok.get("period"))
            if period:
                label = f"{label} {period}"
            values.append(
                QuotaValue(
                    quota_id="grok_bot_weekly",
                    quota_label=label,
                    remaining_percent=remaining,
                    reset_at=parse_iso_datetime(grok.get("reset_at")),
                )
            )
    return values


def _quota_value(quota_id: str, label: str, window: RateWindow, remaining: float) -> QuotaValue:
    return QuotaValue(
        quota_id=quota_id,
        quota_label=label,
        remaining_percent=remaining,
        reset_at=window.reset_at,
        window_seconds=window.window_seconds,
        window_minutes=window.window_minutes,
    )


def _legacy_labels(snapshots: Sequence[QuotaSnapshot]) -> dict[int, str]:
    counts: dict[str, int] = {}
    labels: dict[int, str] = {}
    for index, snapshot in enumerate(snapshots):
        if snapshot.provider == "claude" or snapshot.error is not None or not _quota_values(snapshot):
            continue
        base = _legacy_account_label(snapshot)
        counts[base] = counts.get(base, 0) + 1
        labels[index] = base if counts[base] == 1 else f"{base}-{counts[base]}"
    return labels


def _legacy_account_label(snapshot: QuotaSnapshot) -> str:
    if snapshot.email:
        raw = snapshot.email.split("@", 1)[0]
    elif snapshot.provider_account_id:
        raw = snapshot.provider_account_id
    else:
        raw = snapshot.provider or "account"
    return _token(raw) or "account"


def _stable_account_id(snapshot: QuotaSnapshot) -> str | None:
    for candidate in (snapshot.provider_account_id, snapshot.chatgpt_account_id):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _display_name(snapshot: QuotaSnapshot) -> str:
    if snapshot.email:
        label = snapshot.email.split("@", 1)[0].strip()
        if label:
            return label
    return "Account"


def _observation_to_json(observation: HistoryObservation) -> dict[str, Any]:
    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "recorded_at": isoformat_or_none(observation.recorded_at),
        "provider": observation.provider,
        "account_id": observation.account_id,
        "display_name": observation.display_name,
        "quota_id": observation.quota_id,
        "quota_label": observation.quota_label,
        "remaining_percent": observation.remaining_percent,
        "reset_at": isoformat_or_none(observation.reset_at),
        "legacy_label": observation.legacy_label,
        "window_seconds": observation.window_seconds,
        "window_minutes": observation.window_minutes,
    }


def _remaining_percent(window: RateWindow) -> float | None:
    return _finite_percent(window.remaining_percent)


def _finite_percent(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if not math.isfinite(result):
        return None
    return max(0.0, min(100.0, result))


def _duration_key(window: RateWindow) -> tuple[int | None, int | None] | None:
    if window.window_seconds is None and window.window_minutes is None:
        return None
    return window.window_seconds, window.window_minutes


def _quota_token(value: str) -> str:
    return _token(value).lower().replace("-", "_")


def _token(value: str) -> str:
    return _TOKEN_RE.sub("_", value.strip()).strip("_")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.astimezone(timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_required_timestamp(value: str) -> datetime:
    parsed = parse_iso_datetime(value)
    if parsed is None:
        raise ValueError("invalid history timestamp")
    return parsed


def _optional_positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _nonempty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _latest_quota_label(points: Sequence[HistoryObservation]) -> str:
    return max(points, key=lambda item: item.recorded_at).quota_label if points else ""


def _reset_neighbor_timestamps(
    points: Sequence[HistoryObservation],
    markers: Sequence[datetime],
) -> set[str]:
    if not points or not markers:
        return set()
    result: set[str] = set()
    ordered = sorted(points, key=lambda item: item.recorded_at)
    timestamps = [item.recorded_at for item in ordered]
    for marker in markers:
        index = bisect_left(timestamps, marker)
        if index:
            result.add(isoformat_or_none(ordered[index - 1].recorded_at) or "")
        if index < len(ordered):
            result.add(isoformat_or_none(ordered[index].recorded_at) or "")
    return result


def _downsample_segments(
    segments: Sequence[Sequence[dict[str, Any]]],
    protected_timestamps: set[str],
    max_points: int,
) -> list[list[dict[str, Any]]]:
    total = sum(len(segment) for segment in segments)
    if total <= max_points or max_points <= 0:
        return [list(segment) for segment in segments]
    if len(segments) >= max_points:
        # segmentの端点は欠損区間を表すため、描画点数の上限より優先する。
        return [[segment[0], *([segment[-1]] if len(segment) > 1 else [])] for segment in segments]

    base_budgets = [min(2, len(segment)) for segment in segments]
    base_budget = sum(base_budgets)
    extra_budget = max(0, max_points - base_budget)
    capacities = [max(0, len(segment) - base) for segment, base in zip(segments, base_budgets)]
    total_capacity = max(1, sum(capacities))
    extra_by_segment = [
        min(capacity, extra_budget * capacity // total_capacity)
        for capacity in capacities
    ]
    allocated_extra = sum(extra_by_segment)
    for index, capacity in enumerate(capacities):
        if allocated_extra >= extra_budget:
            break
        if extra_by_segment[index] < capacity:
            extra_by_segment[index] += 1
            allocated_extra += 1
    result: list[list[dict[str, Any]]] = []
    for segment, base, extra in zip(segments, base_budgets, extra_by_segment):
        result.append(_downsample_one(segment, base + extra, protected_timestamps))
    return result


def _downsample_one(
    points: Sequence[dict[str, Any]],
    budget: int,
    protected_timestamps: set[str],
) -> list[dict[str, Any]]:
    if len(points) <= budget:
        return list(points)
    if len(points) <= 2:
        return list(points)

    keep = {0, len(points) - 1}
    keep.update(index for index, point in enumerate(points) if point["timestamp"] in protected_timestamps)
    bucket_count = max(1, (budget - len(keep)) // 2)
    interior_size = len(points) - 2
    for bucket in range(bucket_count):
        start = 1 + interior_size * bucket // bucket_count
        end = 1 + interior_size * (bucket + 1) // bucket_count
        if start >= end:
            continue
        minimum = min(range(start, end), key=lambda index: points[index]["remaining_percent"])
        maximum = max(range(start, end), key=lambda index: points[index]["remaining_percent"])
        keep.add(minimum)
        keep.add(maximum)
    return [points[index] for index in sorted(keep)]
