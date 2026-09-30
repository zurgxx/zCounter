from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from zcounter.models import QuotaSnapshot, RateWindow
from zcounter.ui.usage_history import (
    GAP_THRESHOLD_SECONDS,
    MAX_DRAW_POINTS_PER_CHART,
    HistoryObservation,
    UsageHistoryAPI,
    _downsample_segments,
    _legacy_provider,
    _read_legacy_log,
    append_usage_history,
    build_history_payload,
    read_usage_history,
    split_history_points,
    usage_history_path,
)
from zcounter.ui.usage_log import append_usage_log
from tests.test_usage_log import _codex_snapshot, _cursor_snapshot


def _claude_snapshot(
    account_id: str | None,
    *,
    remaining: float = 73.125,
    reset_at: datetime | None = None,
) -> QuotaSnapshot:
    window = RateWindow(100.0 - remaining, remaining, reset_at, 300, 18_000)
    return QuotaSnapshot(
        provider="claude",
        email="claude@example.com",
        plan="Pro",
        chatgpt_account_id=None,
        five_hour=window,
        weekly=None,
        primary=window,
        primary_label="Session",
        provider_account_id=account_id,
        source="claude-usage",
        updated_at=datetime(2026, 9, 28, tzinfo=timezone.utc),
    )


def _observation(
    recorded_at: datetime,
    *,
    provider: str = "codex",
    account_id: str = "account-1",
    display_name: str = "Main",
    quota_id: str = "five_hour",
    quota_label: str = "Five Hour",
    remaining: float = 75.0,
    reset_at: datetime | None = None,
    source: str = "jsonl",
    legacy_label: str | None = None,
) -> HistoryObservation:
    return HistoryObservation(
        recorded_at=recorded_at,
        provider=provider,
        account_id=account_id,
        display_name=display_name,
        quota_id=quota_id,
        quota_label=quota_label,
        remaining_percent=remaining,
        reset_at=reset_at,
        source=source,
        legacy_label=legacy_label,
    )


class UsageHistoryWriterTests(unittest.TestCase):
    def test_writer_emits_one_utc_jsonl_row_per_account_quota_and_keeps_precision(self) -> None:
        recorded_at = datetime(2026, 9, 28, 12, 30, tzinfo=timezone(timedelta(hours=9)))
        reset_at = datetime(2026, 9, 28, 17, tzinfo=timezone(timedelta(hours=9)))
        codex = _codex_snapshot("codex-main@example.com")
        codex = QuotaSnapshot(
            **{
                **codex.__dict__,
                "five_hour": RateWindow(28.875, 71.125, reset_at, 300, 18_000),
                "primary": RateWindow(28.875, 71.125, reset_at, 300, 18_000),
            }
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage-history.jsonl"
            self.assertTrue(append_usage_history([codex, _cursor_snapshot()], recorded_at, path))
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(rows), 4)
        self.assertEqual({row["provider"] for row in rows}, {"codex", "cursor"})
        self.assertEqual(rows[0]["recorded_at"], "2026-09-28T03:30:00Z")
        self.assertEqual(rows[0]["reset_at"], "2026-09-28T08:00:00Z")
        self.assertEqual(rows[0]["remaining_percent"], 71.125)
        self.assertEqual(rows[0]["account_id"], "codex-main@example.com")
        self.assertEqual(rows[0]["display_name"], "codex-main")
        self.assertEqual(
            {(row["quota_id"], row["quota_label"]) for row in rows if row["provider"] == "codex"},
            {("five_hour", "Five Hour"), ("weekly", "Weekly")},
        )
        self.assertEqual(
            {row["quota_id"] for row in rows if row["provider"] == "cursor"},
            {"total", "first_party_models"},
        )

    def test_claude_is_written_only_when_snapshot_has_a_stable_account_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage-history.jsonl"
            self.assertFalse(append_usage_history([_claude_snapshot(None)], datetime.now(timezone.utc), path))
            self.assertFalse(path.exists())
            self.assertTrue(
                append_usage_history(
                    [_claude_snapshot("claude-uuid", reset_at=datetime(2026, 9, 28, 13, tzinfo=timezone.utc))],
                    datetime(2026, 9, 28, 12, tzinfo=timezone.utc),
                    path,
                )
            )
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider"], "claude")
        self.assertEqual(rows[0]["account_id"], "claude-uuid")
        self.assertEqual(rows[0]["quota_id"], "five_hour")
        self.assertEqual(rows[0]["remaining_percent"], 73.125)

    def test_history_writer_does_not_modify_or_mix_with_legacy_usage_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            legacy_path = Path(directory) / "usage.log"
            history_path = Path(directory) / "usage-history.jsonl"
            timestamp = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
            self.assertTrue(append_usage_log([_codex_snapshot("codex-main@example.com")], timestamp, legacy_path))
            before = legacy_path.read_bytes()
            self.assertTrue(append_usage_history([_codex_snapshot("codex-main@example.com")], timestamp, history_path))
            self.assertEqual(legacy_path.read_bytes(), before)
            self.assertTrue(legacy_path.read_text(encoding="utf-8").startswith("2026-09-28 "))
            self.assertTrue(history_path.read_text(encoding="utf-8").lstrip().startswith("{"))

    def test_history_path_uses_state_directory_or_explicit_override(self) -> None:
        with mock.patch.dict("os.environ", {"XDG_STATE_HOME": "/tmp/zcounter-state"}, clear=True):
            self.assertEqual(
                usage_history_path(),
                Path("/tmp/zcounter-state/zcounter/usage-history.jsonl"),
            )
        with mock.patch.dict(
            "os.environ", {"ZCOUNTER_USAGE_HISTORY": "~/history.jsonl"}, clear=True
        ):
            self.assertEqual(usage_history_path(), Path.home() / "history.jsonl")


class UsageHistoryReadTests(unittest.TestCase):
    def test_legacy_provider_classification_uses_disjoint_signatures(self) -> None:
        self.assertEqual(_legacy_provider({"five_hour", "weekly"}), "codex")
        self.assertEqual(_legacy_provider({"total", "first_party_models", "api", "grok_bot_weekly"}), "cursor")
        self.assertEqual(_legacy_provider({"api"}), "cursor")
        self.assertIsNone(_legacy_provider({"five_hour", "total"}))
        self.assertIsNone(_legacy_provider({"unknown"}))

    def test_legacy_usage_log_rows_are_parsed_as_separate_provider_quota_series(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            legacy_path = Path(directory) / "usage.log"
            history_path = Path(directory) / "usage-history.jsonl"
            legacy_path.write_text(
                "2026-09-28 10:00:00 codex:five_hour=80%,weekly=61% "
                "cursor:total=82%,first_party_models=74%,api=100%,grok_bot_weekly=90% "
                "ambiguous:five_hour=50%,total=40% unknown:other=20%\n",
                encoding="utf-8",
            )
            observations = _read_legacy_log(legacy_path)

        codex = [item for item in observations if item.provider == "codex"]
        cursor = [item for item in observations if item.provider == "cursor"]
        self.assertEqual({item.quota_id for item in codex}, {"five_hour", "weekly"})
        self.assertEqual(
            {item.quota_id for item in cursor},
            {"total", "first_party_models", "api", "grok_bot_weekly"},
        )
        self.assertTrue(all(item.source == "legacy" and item.reset_at is None for item in observations))
        self.assertTrue(all(item.account_id.startswith("legacy:") for item in observations))

    def test_history_defaults_to_jsonl_only_and_selector_contains_only_stable_series(self) -> None:
        timestamp = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
        snapshots = [
            _codex_snapshot("rock@example.com"),
            _codex_snapshot("zurgxx@example.com"),
            _cursor_snapshot(email="rock@example.com"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            history_path = Path(directory) / "usage-history.jsonl"
            legacy_path = Path(directory) / "usage.log"
            self.assertTrue(append_usage_history(snapshots, timestamp, history_path))
            legacy_path.write_text(
                "2026-09-28 10:00:00 codex-main:five_hour=80%,weekly=60% "
                "cursor:total=80%,first_party_models=70% "
                "rock-1:total=75%,first_party_models=65% "
                "rock-2:total=70%,first_party_models=60%\n",
                encoding="utf-8",
            )
            with mock.patch("zcounter.ui.usage_history._read_legacy_log") as legacy_reader:
                observations = read_usage_history(history_path, legacy_path)
            legacy_reader.assert_not_called()

        codex = build_history_payload(observations, "codex", None, "all", timestamp)
        cursor = build_history_payload(observations, "cursor", None, "all", timestamp)
        self.assertEqual([item["label"] for item in codex["accounts"]], ["rock", "zurgxx"])
        self.assertEqual([item["label"] for item in cursor["accounts"]], ["rock"])
        self.assertEqual({item.source for item in observations}, {"jsonl"})
        self.assertNotIn("codex-main", {item["label"] for item in codex["accounts"]})
        self.assertNotIn("cursor", {item["label"] for item in cursor["accounts"]})

    def test_legacy_log_can_be_reenabled_without_changing_its_parser(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history_path = Path(directory) / "usage-history.jsonl"
            legacy_path = Path(directory) / "usage.log"
            legacy_path.write_text(
                "2026-09-28 10:00:00 codex-main:five_hour=80%,weekly=60%\n",
                encoding="utf-8",
            )
            with mock.patch("zcounter.ui.usage_history.INCLUDE_LEGACY_USAGE_LOG", True):
                observations = read_usage_history(history_path, legacy_path)

        self.assertEqual({item.provider for item in observations}, {"codex"})
        self.assertEqual({item.source for item in observations}, {"legacy"})

    def test_legacy_series_connects_only_when_structured_alias_has_one_stable_id(self) -> None:
        timestamp = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            history_path = Path(directory) / "usage-history.jsonl"
            legacy_path = Path(directory) / "usage.log"
            snapshots = [
                _codex_snapshot("codex-main@example.com"),
                _cursor_snapshot(),
            ]
            self.assertTrue(
                append_usage_history(snapshots, timestamp, history_path)
            )
            old_timestamp = timestamp - timedelta(minutes=10)
            append_usage_log(snapshots, old_timestamp, legacy_path)
            with mock.patch("zcounter.ui.usage_history.INCLUDE_LEGACY_USAGE_LOG", True):
                observations = read_usage_history(history_path, legacy_path)

        self.assertEqual(
            {item.account_id for item in observations},
            {"codex-main@example.com", "cursor-id"},
        )
        self.assertEqual({item.source for item in observations}, {"legacy", "jsonl"})
        self.assertEqual(len(observations), 8)

    def test_same_timestamp_grok_legacy_copy_deduplicates_by_quota_id(self) -> None:
        timestamp = datetime(2026, 9, 28, 12, 5, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            history_path = Path(directory) / "usage-history.jsonl"
            legacy_path = Path(directory) / "usage.log"
            snapshot = _cursor_snapshot(grok_remaining=91.25)
            append_usage_history([snapshot], timestamp, history_path)
            append_usage_log([snapshot], timestamp, legacy_path)
            with mock.patch("zcounter.ui.usage_history.INCLUDE_LEGACY_USAGE_LOG", True):
                observations = read_usage_history(history_path, legacy_path)

        grok_rows = [item for item in observations if item.quota_id == "grok_bot_weekly"]
        self.assertEqual(len(grok_rows), 1)
        self.assertEqual(grok_rows[0].source, "jsonl")

    def test_ambiguous_legacy_alias_remains_an_independent_legacy_series(self) -> None:
        timestamp = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            history_path = Path(directory) / "usage-history.jsonl"
            legacy_path = Path(directory) / "usage.log"
            append_usage_history([_codex_snapshot("same@example.com")], timestamp, history_path)
            second = _codex_snapshot("same@example.com")
            second = QuotaSnapshot(**{**second.__dict__, "provider_account_id": "stable-id-2", "chatgpt_account_id": "stable-id-2"})
            append_usage_history([second], timestamp + timedelta(minutes=1), history_path)
            append_usage_log(
                [_codex_snapshot("same@example.com")],
                timestamp - timedelta(minutes=10),
                legacy_path,
            )
            with mock.patch("zcounter.ui.usage_history.INCLUDE_LEGACY_USAGE_LOG", True):
                observations = read_usage_history(history_path, legacy_path)

        legacy = [item for item in observations if item.source == "legacy"]
        self.assertEqual(len(legacy), 2)
        self.assertEqual({item.account_id for item in legacy}, {"legacy:codex:same"})

    def test_corrupt_rows_and_unknown_schema_are_skipped_without_losing_valid_history(self) -> None:
        valid = {
            "schema_version": 1,
            "recorded_at": "2026-09-28T12:00:00Z",
            "provider": "codex",
            "account_id": "stable-id",
            "display_name": "Main",
            "quota_id": "weekly",
            "quota_label": "Weekly",
            "remaining_percent": 12.375,
            "reset_at": None,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage-history.jsonl"
            path.write_text(
                "{broken json\n"
                + json.dumps({**valid, "schema_version": 2})
                + "\n"
                + json.dumps({**valid, "remaining_percent": float("nan")})
                + "\n"
                + json.dumps({**valid, "schema_version": True})
                + "\n"
                + json.dumps(valid)
                + "\n",
                encoding="utf-8",
            )
            observations = read_usage_history(path, Path(directory) / "missing.log")

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].remaining_percent, 12.375)
        self.assertEqual(observations[0].recorded_at, datetime(2026, 9, 28, 12, tzinfo=timezone.utc))


class UsageHistoryPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)

    def test_account_and_quota_series_are_separate_and_period_filters_are_correct(self) -> None:
        offsets = (-40, -29, -8, -6, -1, 0)
        observations = [
            _observation(self.now + timedelta(days=offset), remaining=float(80 + index))
            for index, offset in enumerate(offsets)
        ]
        observations.extend(
            [
                _observation(
                    self.now - timedelta(hours=2),
                    account_id="account-2",
                    display_name="Main",
                    remaining=40.0,
                ),
                _observation(
                    self.now - timedelta(hours=1),
                    quota_id="weekly",
                    quota_label="Weekly",
                    remaining=65.0,
                ),
                _observation(
                    self.now - timedelta(hours=1),
                    provider="cursor",
                    account_id="cursor-id",
                    display_name="Cursor",
                    quota_id="total",
                    quota_label="Total",
                    remaining=50.0,
                ),
            ]
        )

        counts = {}
        for period in ("1h", "5h", "24h", "7d", "30d", "all"):
            payload = build_history_payload(observations, "codex", "account-1", period, self.now)
            five_hour = next(chart for chart in payload["charts"] if chart["quota_id"] == "five_hour")
            counts[period] = sum(len(segment) for segment in five_hour["segments"])
        self.assertEqual(counts, {"1h": 1, "5h": 1, "24h": 2, "7d": 3, "30d": 5, "all": 6})

        selected = build_history_payload(observations, "codex", "account-2", "all", self.now)
        self.assertEqual(selected["selected_account_id"], "account-2")
        self.assertEqual(len(selected["charts"]), 1)
        self.assertEqual(selected["charts"][0]["quota_id"], "five_hour")
        duplicate_name_labels = {account["label"] for account in selected["accounts"]}
        self.assertEqual(len(duplicate_name_labels), 2)
        cursor = build_history_payload(observations, "cursor", None, "24h", self.now)
        self.assertEqual([item["quota_id"] for item in cursor["charts"]], ["total"])

    def test_one_hour_period_includes_boundaries_and_excludes_older_and_future_points(self) -> None:
        observations = [
            _observation(self.now + timedelta(seconds=offset), remaining=float(index))
            for index, offset in enumerate((-7200, -3601, -3600, -1800, 0, 1))
        ]
        payload = build_history_payload(observations, period="1H", now=self.now)

        self.assertEqual(payload["period"], "1h")
        self.assertEqual(payload["range_start"], "2026-09-28T11:00:00Z")
        self.assertEqual(payload["range_end"], "2026-09-28T12:00:00Z")
        points = [point for segment in payload["charts"][0]["segments"] for point in segment]
        self.assertEqual([point["remaining_percent"] for point in points], [2.0, 3.0, 4.0])

        default_payload = build_history_payload(observations, now=self.now)
        self.assertEqual(default_payload["period"], "5h")
        self.assertEqual(default_payload["range_start"], "2026-09-28T07:00:00Z")

    def test_period_aliases_and_invalid_filters_are_safe(self) -> None:
        observations = [_observation(self.now)]
        payload = build_history_payload(observations, provider=[], account_id=[], period=None, now=self.now)
        self.assertEqual(payload["provider"], "codex")
        self.assertEqual(payload["period"], "5h")
        self.assertEqual(payload["selected_account_id"], "account-1")

    def test_six_minute_gap_boundary_is_contiguous_but_longer_gap_is_cut(self) -> None:
        start = self.now - timedelta(minutes=20)
        points = [
            {"timestamp": start.isoformat(), "remaining_percent": 90.0},
            {"timestamp": (start + timedelta(seconds=GAP_THRESHOLD_SECONDS)).isoformat(), "remaining_percent": 80.0},
            {"timestamp": (start + timedelta(seconds=GAP_THRESHOLD_SECONDS + 361)).isoformat(), "remaining_percent": 20.0},
        ]
        segments, gaps = split_history_points(points)
        self.assertEqual([len(segment) for segment in segments], [2, 1])
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["duration_seconds"], 361.0)

    def test_reset_markers_and_next_reset_are_only_created_from_structured_points(self) -> None:
        upcoming_reset = self.now + timedelta(minutes=30)
        structured = _observation(
            self.now - timedelta(minutes=5),
            reset_at=upcoming_reset,
            remaining=55.25,
        )
        past_reset = self.now - timedelta(hours=1)
        reset_observation = _observation(
            self.now - timedelta(hours=2),
            reset_at=past_reset,
            remaining=80.0,
        )
        legacy = _observation(
            self.now - timedelta(hours=3),
            remaining=85.0,
            source="legacy",
        )
        payload = build_history_payload(
            [legacy, reset_observation, structured], "codex", "account-1", "24h", self.now
        )
        chart = payload["charts"][0]
        self.assertEqual(chart["reset_markers"], ["2026-09-28T11:00:00Z"])
        self.assertEqual(chart["next_reset"], "2026-09-28T12:30:00Z")
        self.assertEqual(chart["segments"][0][0]["source"], "legacy")

        legacy_only = build_history_payload(
            [_observation(self.now - timedelta(hours=3), source="legacy")],
            "codex",
            "account-1",
            "24h",
            self.now,
        )["charts"][0]
        self.assertEqual(legacy_only["reset_markers"], [])
        self.assertIsNone(legacy_only["next_reset"])

    def test_all_period_downsampling_preserves_endpoints_extrema_gap_and_reset_neighbors(self) -> None:
        start = self.now - timedelta(days=4)
        points = []
        for index in range(2_500):
            value = 50.0
            if index == 455:
                value = 0.0
            elif index == 456:
                value = 100.0
            points.append(
                {
                    "timestamp": (start + timedelta(seconds=index * 60)).isoformat().replace("+00:00", "Z"),
                    "remaining_percent": value,
                    "source": "jsonl",
                }
            )
        reset_point = points[1_003]["timestamp"]
        protected = {reset_point}
        segments, gaps = split_history_points(points)
        self.assertEqual(gaps, [])
        reduced = _downsample_segments(segments, protected, MAX_DRAW_POINTS_PER_CHART)
        retained = reduced[0]
        self.assertLessEqual(len(retained), MAX_DRAW_POINTS_PER_CHART)
        self.assertEqual(retained[0], points[0])
        self.assertEqual(retained[-1], points[-1])
        self.assertEqual(min(point["remaining_percent"] for point in retained), 0.0)
        self.assertEqual(max(point["remaining_percent"] for point in retained), 100.0)
        self.assertIn(reset_point, {point["timestamp"] for point in retained})

    def test_usage_history_api_reads_only_jsonl_with_selected_period(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history_path = Path(directory) / "usage-history.jsonl"
            legacy_path = Path(directory) / "usage.log"
            append_usage_history([_codex_snapshot("codex-main@example.com")], self.now, history_path)
            append_usage_log(
                [_codex_snapshot("legacy-only@example.com")],
                self.now - timedelta(minutes=10),
                legacy_path,
            )
            api = UsageHistoryAPI(history_path, legacy_path, now_fn=lambda: self.now)
            payload = api.get_history("codex", None, "ALL")

        self.assertEqual(payload["period"], "all")
        self.assertEqual(payload["selected_account_id"], "codex-main@example.com")
        self.assertEqual([account["label"] for account in payload["accounts"]], ["codex-main"])
        self.assertEqual({chart["quota_id"] for chart in payload["charts"]}, {"five_hour", "weekly"})


if __name__ == "__main__":
    unittest.main()
