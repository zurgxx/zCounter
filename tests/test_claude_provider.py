from __future__ import annotations

import datetime
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from zcounter.cli import _row
from zcounter.providers.claude import provider, usage_api
from zcounter.providers.claude.auth import ClaudeAuth
from zcounter.providers.claude.provider import ClaudeUsageShapeError, normalize_claude_snapshot
from zcounter.providers.claude import rate_limit_gate
from zcounter.providers.claude.usage_api import (
    ClaudeAPIError,
    ClaudeRateLimitedError,
    ClaudeShapeError,
    ClaudeUnauthorizedError,
    RATE_LIMIT_MESSAGE,
    fetch_usage,
)
from zcounter.providers.aggregate import fetch_all_quotas


class ClaudeProviderTests(unittest.TestCase):
    def test_claude_minimal_payload_five_hour_and_week(self) -> None:
        snapshot = normalize_claude_snapshot(
            {
                "five_hour": {
                    "utilization": 20.0,
                    "resets_at": "2026-06-12T04:59:59.547264+00:00",
                },
                "seven_day": {
                    "utilization": 40.0,
                    "resets_at": "2026-06-16T12:59:59.547282+00:00",
                },
            },
            {
                "account": {
                    "email": "user@example.com",
                    "uuid": "449a2cf0-5d3c-4d29-8fb6-13ad4c798f77",
                    "has_claude_pro": True,
                    "has_claude_max": False,
                },
                "organization": {"organization_type": "claude_pro"},
            },
            ClaudeAuth(
                path=Path("/tmp/.credentials.json"),
                access_token="redacted",
                subscription_type="pro",
                rate_limit_tier="default_claude_ai",
            ),
        )

        self.assertEqual(snapshot.provider, "claude")
        self.assertEqual(snapshot.email, "user@example.com")
        self.assertEqual(snapshot.plan, "Pro")
        self.assertEqual(snapshot.primary_label, "5H")
        self.assertEqual(snapshot.secondary_label, "WEEK")
        self.assertEqual(snapshot.source, "claude-usage")
        self.assertIsNotNone(snapshot.primary)
        self.assertEqual(snapshot.primary.used_percent, 20.0)
        self.assertEqual(snapshot.primary.remaining_percent, 80.0)
        self.assertEqual(snapshot.primary.window_minutes, 300)
        self.assertIsNotNone(snapshot.secondary)
        self.assertEqual(snapshot.secondary.used_percent, 40.0)
        self.assertEqual(snapshot.secondary.remaining_percent, 60.0)
        self.assertEqual(snapshot.secondary.window_minutes, 10_080)

        row = _row(snapshot)
        self.assertEqual(row[3], "5H 80%")
        self.assertEqual(row[4], "20%")
        self.assertEqual(row[5], "WEEK 60%")
        self.assertEqual(row[6], "40%")

    def test_utilization_one_means_one_percent_not_full(self) -> None:
        snapshot = normalize_claude_snapshot(
            {
                "five_hour": {"utilization": 11.0, "resets_at": "2026-06-12T04:59:59+00:00"},
                "seven_day": {"utilization": 1.0, "resets_at": "2026-06-16T12:59:59+00:00"},
            },
            None,
            ClaudeAuth(
                path=Path("/tmp/.credentials.json"),
                access_token="redacted",
                subscription_type="pro",
                rate_limit_tier=None,
            ),
        )

        self.assertIsNotNone(snapshot.primary)
        self.assertEqual(snapshot.primary.used_percent, 11.0)
        self.assertEqual(snapshot.primary.remaining_percent, 89.0)
        self.assertIsNotNone(snapshot.secondary)
        self.assertEqual(snapshot.secondary.used_percent, 1.0)
        self.assertEqual(snapshot.secondary.remaining_percent, 99.0)

    def test_utilization_whole_number_98_stays_98_percent(self) -> None:
        snapshot = normalize_claude_snapshot(
            {
                "five_hour": {"utilization": 98.0, "resets_at": "2026-06-12T04:59:59+00:00"},
                "seven_day": {"utilization": 0.0, "resets_at": "2026-06-16T12:59:59+00:00"},
            },
            None,
            ClaudeAuth(
                path=Path("/tmp/.credentials.json"),
                access_token="redacted",
                subscription_type="pro",
                rate_limit_tier=None,
            ),
        )

        self.assertIsNotNone(snapshot.primary)
        self.assertEqual(snapshot.primary.used_percent, 98.0)

    def test_missing_or_invalid_utilization_does_not_crash(self) -> None:
        auth = ClaudeAuth(
            path=Path("/tmp/.credentials.json"),
            access_token="redacted",
            subscription_type="pro",
            rate_limit_tier=None,
        )
        snapshot = normalize_claude_snapshot(
            {
                "five_hour": {"utilization": 10.0, "resets_at": "2026-06-12T04:59:59+00:00"},
                "seven_day": {"utilization": None, "resets_at": "2026-06-16T12:59:59+00:00"},
            },
            None,
            auth,
        )

        self.assertIsNotNone(snapshot.primary)
        self.assertIsNone(snapshot.secondary)

        with self.assertRaises(ClaudeUsageShapeError):
            normalize_claude_snapshot(
                {
                    "five_hour": {"utilization": None},
                    "seven_day": {"utilization": "unexpected"},
                },
                None,
                auth,
            )

    def test_claude_whole_number_utilization_is_used_directly(self) -> None:
        snapshot = normalize_claude_snapshot(
            {
                "five_hour": {"utilization": 20.0, "resets_at": "2026-06-12T04:59:59+00:00"},
                "seven_day": {"utilization": 40.0, "resets_at": "2026-06-16T12:59:59+00:00"},
            },
            None,
            ClaudeAuth(
                path=Path("/tmp/.credentials.json"),
                access_token="redacted",
                subscription_type="pro",
                rate_limit_tier=None,
            ),
        )

        self.assertIsNotNone(snapshot.primary)
        self.assertEqual(snapshot.primary.used_percent, 20.0)
        self.assertIsNotNone(snapshot.secondary)
        self.assertEqual(snapshot.secondary.used_percent, 40.0)

    def test_claude_max_plan_from_profile(self) -> None:
        snapshot = normalize_claude_snapshot(
            {"five_hour": {"utilization": 5.0, "resets_at": "2026-06-12T04:59:59+00:00"}},
            {
                "account": {"has_claude_max": True, "has_claude_pro": False},
                "organization": {"organization_type": "claude_max"},
            },
            ClaudeAuth(
                path=Path("/tmp/.credentials.json"),
                access_token="redacted",
                subscription_type="max",
                rate_limit_tier=None,
            ),
        )

        self.assertEqual(snapshot.plan, "Max")

    def test_auto_refresh_skips_profile_and_uses_credentials_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            creds = Path(tmp) / ".credentials.json"
            creds.write_text(
                json.dumps(
                    {
                        "claudeAiOauth": {
                            "accessToken": "redacted",
                            "subscriptionType": "pro",
                        }
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": tmp}, clear=False):
                with mock.patch.object(
                    provider,
                    "fetch_usage",
                    return_value={
                        "five_hour": {"utilization": 12.0, "resets_at": "2026-06-12T04:59:59+00:00"},
                        "seven_day": {"utilization": 3.0, "resets_at": "2026-06-16T12:59:59+00:00"},
                    },
                ):
                    with mock.patch.object(provider, "fetch_profile") as fetch_profile_mock:
                        snapshot = provider.fetch_claude_quota(user_initiated=False)

        fetch_profile_mock.assert_not_called()
        self.assertIsNone(snapshot.error)
        self.assertIsNone(snapshot.email)
        self.assertEqual(snapshot.plan, "Pro")
        self.assertIsNotNone(snapshot.primary)
        self.assertEqual(snapshot.primary.used_percent, 12.0)

    def test_user_refresh_fetches_profile_when_cache_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            creds = Path(tmp) / ".credentials.json"
            creds.write_text(
                json.dumps(
                    {
                        "claudeAiOauth": {
                            "accessToken": "redacted",
                            "subscriptionType": "pro",
                        }
                    }
                ),
                encoding="utf-8",
            )
            profile_cache = Path(tmp) / "profile-cache.json"
            with mock.patch.dict(
                "os.environ",
                {
                    "CLAUDE_CONFIG_DIR": tmp,
                    "ZCOUNTER_CLAUDE_PROFILE_CACHE": str(profile_cache),
                },
                clear=False,
            ):
                with mock.patch.object(
                    provider,
                    "fetch_usage",
                    return_value={
                        "five_hour": {"utilization": 12.0, "resets_at": "2026-06-12T04:59:59+00:00"},
                        "seven_day": {"utilization": 3.0, "resets_at": "2026-06-16T12:59:59+00:00"},
                    },
                ):
                    with mock.patch.object(
                        provider,
                        "fetch_profile",
                        return_value={
                            "account": {
                                "email": "user@example.com",
                                "uuid": "449a2cf0-5d3c-4d29-8fb6-13ad4c798f77",
                            }
                        },
                    ) as fetch_profile_mock:
                        snapshot = provider.fetch_claude_quota(user_initiated=True)

        fetch_profile_mock.assert_called_once()
        self.assertIsNone(snapshot.error)
        self.assertEqual(snapshot.email, "user@example.com")
        self.assertEqual(snapshot.plan, "Pro")

    def test_malformed_credentials_json_returns_error_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            creds = Path(tmp) / ".credentials.json"
            creds.write_text("{not json", encoding="utf-8")
            with mock.patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": tmp}, clear=True):
                snapshot = provider.fetch_claude_quota()

        self.assertEqual(snapshot.provider, "claude")
        self.assertIn("not valid JSON", snapshot.error)
        self.assertNotIn("accessToken", snapshot.error)

    def test_malformed_credentials_missing_oauth_returns_error_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            creds = Path(tmp) / ".credentials.json"
            creds.write_text(json.dumps({"other": {}}), encoding="utf-8")
            with mock.patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": tmp}, clear=True):
                snapshot = provider.fetch_claude_quota()

        self.assertEqual(snapshot.provider, "claude")
        self.assertIn("missing claudeAiOauth", snapshot.error)

    def test_missing_credentials_returns_secret_free_error_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": tmp}, clear=True):
                snapshot = provider.fetch_claude_quota()

        self.assertEqual(snapshot.provider, "claude")
        self.assertIn("claude credentials were not found", snapshot.error)
        self.assertNotIn("accessToken", snapshot.error)

    def test_unauthorized_error_is_secret_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            creds = Path(tmp) / ".credentials.json"
            creds.write_text(
                json.dumps({"claudeAiOauth": {"accessToken": "redacted"}}),
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": tmp}, clear=False):
                with mock.patch.object(
                    provider,
                    "fetch_usage",
                    side_effect=ClaudeUnauthorizedError("Claude Code login required or token expired"),
                ):
                    snapshot = provider.fetch_claude_quota()

        self.assertEqual(snapshot.error, "Claude Code login required or token expired")
        self.assertNotIn("redacted", snapshot.error)

    def test_http_401_maps_to_login_required_message(self) -> None:
        def fail(*args, **kwargs):
            raise urllib.error.HTTPError(
                usage_api.USAGE_URL,
                401,
                "unauthorized",
                hdrs=None,
                fp=None,
            )

        with mock.patch.object(usage_api.urllib.request, "urlopen", side_effect=fail):
            with self.assertRaises(ClaudeUnauthorizedError) as raised:
                fetch_usage("redacted")

        self.assertEqual(str(raised.exception), "Claude Code login required or token expired")
        self.assertNotIn("redacted", str(raised.exception))

    def test_http_403_maps_to_login_required_message(self) -> None:
        def fail(*args, **kwargs):
            raise urllib.error.HTTPError(
                usage_api.USAGE_URL,
                403,
                "forbidden",
                hdrs=None,
                fp=None,
            )

        with mock.patch.object(usage_api.urllib.request, "urlopen", side_effect=fail):
            with self.assertRaises(ClaudeUnauthorizedError) as raised:
                fetch_usage("redacted")

        self.assertEqual(str(raised.exception), "Claude Code login required or token expired")

    def test_claude_failure_does_not_block_other_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": tmp}, clear=False):
                with mock.patch("zcounter.providers.aggregate.fetch_codex_quotas", return_value=[]):
                    with mock.patch(
                        "zcounter.providers.aggregate.fetch_cursor_quota_if_configured",
                        return_value=None,
                    ):
                        snapshots = fetch_all_quotas()

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].provider, "claude")
        self.assertIn("credentials were not found", snapshots[0].error)

    def test_http_error_does_not_include_token(self) -> None:
        def fail(*args, **kwargs):
            raise urllib.error.HTTPError(
                usage_api.USAGE_URL,
                500,
                "server rejected redacted",
                hdrs=None,
                fp=None,
            )

        with mock.patch.object(usage_api.urllib.request, "urlopen", side_effect=fail):
            with self.assertRaises(ClaudeAPIError) as raised:
                usage_api.fetch_usage("redacted")

        self.assertNotIn("redacted", str(raised.exception))

    def test_parse_error_does_not_include_token(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"not json"

        with mock.patch.object(usage_api.urllib.request, "urlopen", return_value=Response()):
            with self.assertRaises(ClaudeShapeError) as raised:
                usage_api.fetch_usage("redacted")

        self.assertNotIn("redacted", str(raised.exception))

    def test_no_usable_quota_returns_error_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            creds = Path(tmp) / ".credentials.json"
            creds.write_text(
                json.dumps({"claudeAiOauth": {"accessToken": "redacted"}}),
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": tmp}, clear=False):
                with mock.patch.object(provider, "fetch_usage", return_value={}):
                    snapshot = provider.fetch_claude_quota()

        self.assertIn("no usable quota", snapshot.error)

    def test_http_429_records_cooldown_and_returns_actionable_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "rate-limit.json"
            creds = Path(tmp) / ".credentials.json"
            creds.write_text(
                json.dumps({"claudeAiOauth": {"accessToken": "redacted"}}),
                encoding="utf-8",
            )
            with mock.patch.dict(
                "os.environ",
                {
                    "CLAUDE_CONFIG_DIR": tmp,
                    "ZCOUNTER_CLAUDE_RATE_LIMIT_STATE": str(state_path),
                },
                clear=False,
            ):
                rate_limit_gate.clear()

                def fail(*args, **kwargs):
                    raise urllib.error.HTTPError(
                        usage_api.USAGE_URL,
                        429,
                        "too many requests",
                        hdrs={"Retry-After": "120"},
                        fp=None,
                    )

                with mock.patch.object(usage_api.urllib.request, "urlopen", side_effect=fail):
                    snapshot = provider.fetch_claude_quota(user_initiated=True)

                self.assertEqual(snapshot.error, RATE_LIMIT_MESSAGE)
                self.assertIsNotNone(rate_limit_gate.current_blocked_until())

    def test_rate_limit_gate_blocks_background_refresh_without_http_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "rate-limit.json"
            creds = Path(tmp) / ".credentials.json"
            creds.write_text(
                json.dumps({"claudeAiOauth": {"accessToken": "redacted"}}),
                encoding="utf-8",
            )
            now = datetime.datetime(2026, 6, 12, 12, 0, tzinfo=datetime.timezone.utc)
            with mock.patch.dict(
                "os.environ",
                {
                    "CLAUDE_CONFIG_DIR": tmp,
                    "ZCOUNTER_CLAUDE_RATE_LIMIT_STATE": str(state_path),
                },
                clear=False,
            ):
                rate_limit_gate.record_rate_limit(
                    now + datetime.timedelta(minutes=5),
                    now=now,
                )
                with mock.patch.object(usage_api.urllib.request, "urlopen") as urlopen_mock:
                    snapshot = provider.fetch_claude_quota(user_initiated=False)

        urlopen_mock.assert_not_called()
        self.assertEqual(snapshot.error, RATE_LIMIT_MESSAGE)

    def test_rate_limit_gate_allows_user_refresh_during_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "rate-limit.json"
            creds = Path(tmp) / ".credentials.json"
            creds.write_text(
                json.dumps({"claudeAiOauth": {"accessToken": "redacted"}}),
                encoding="utf-8",
            )
            now = datetime.datetime(2026, 6, 12, 12, 0, tzinfo=datetime.timezone.utc)
            with mock.patch.dict(
                "os.environ",
                {
                    "CLAUDE_CONFIG_DIR": tmp,
                    "ZCOUNTER_CLAUDE_RATE_LIMIT_STATE": str(state_path),
                },
                clear=False,
            ):
                rate_limit_gate.record_rate_limit(
                    now + datetime.timedelta(minutes=5),
                    now=now,
                )
                with mock.patch.object(
                    provider,
                    "fetch_usage",
                    return_value={
                        "five_hour": {"utilization": 1.0, "resets_at": "2026-06-12T04:59:59+00:00"},
                    },
                ) as fetch_usage_mock:
                    snapshot = provider.fetch_claude_quota(user_initiated=True)

        fetch_usage_mock.assert_called_once()
        self.assertIsNone(snapshot.error)


if __name__ == "__main__":
    unittest.main()
