from __future__ import annotations

import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from zcounter.cli import _row
from zcounter.providers.cursor import provider, usage_api
from zcounter.providers.cursor.provider import normalize_cursor_snapshot
from zcounter.providers.cursor.usage_api import CursorAPIError, CursorShapeError, CursorUnauthorizedError


class CursorProviderTests(unittest.TestCase):
    def test_cursor_pro_minimal_payload_total_and_auto_percent(self) -> None:
        snapshot = normalize_cursor_snapshot(
            {
                "billingCycleEnd": "2026-04-18T20:45:42.000Z",
                "membershipType": "pro",
                "individualUsage": {
                    "plan": {
                        "used": 86,
                        "limit": 2000,
                        "totalPercentUsed": 0.441025641025641,
                        "autoPercentUsed": 0.36,
                        "apiPercentUsed": 0.7111111111111111,
                    }
                },
            },
            {"email": "user@example.com", "sub": "auth0|example"},
        )

        self.assertEqual(snapshot.provider, "cursor")
        self.assertEqual(snapshot.email, "user@example.com")
        self.assertEqual(snapshot.plan, "Cursor Pro")
        self.assertEqual(snapshot.primary_label, "Total")
        self.assertEqual(snapshot.secondary_label, "Auto")
        self.assertIsNotNone(snapshot.primary)
        self.assertAlmostEqual(snapshot.primary.used_percent, 44.1025641025641)
        self.assertIsNotNone(snapshot.secondary)
        self.assertEqual(snapshot.secondary.used_percent, 36.0)
        self.assertAlmostEqual(snapshot.primary.remaining_percent, 55.8974358974359)
        self.assertAlmostEqual(snapshot.details["api_used_percent"], 71.11111111111111)

    def test_cursor_fractional_percent_fields_are_scaled_to_display_percent(self) -> None:
        snapshot = normalize_cursor_snapshot(
            {
                "individualUsage": {
                    "plan": {
                        "totalPercentUsed": 0.5,
                        "autoPercentUsed": 12.5,
                    }
                },
            },
            None,
        )

        self.assertIsNotNone(snapshot.primary)
        self.assertEqual(snapshot.primary.used_percent, 50.0)
        self.assertIsNotNone(snapshot.secondary)
        self.assertEqual(snapshot.secondary.used_percent, 12.5)

    def test_cursor_whole_number_percent_fields_are_kept_as_display_percent(self) -> None:
        snapshot = normalize_cursor_snapshot(
            {
                "individualUsage": {
                    "plan": {
                        "totalPercentUsed": 44,
                        "autoPercentUsed": 8,
                    }
                },
            },
            None,
        )

        self.assertIsNotNone(snapshot.primary)
        self.assertEqual(snapshot.primary.used_percent, 44.0)
        self.assertIsNotNone(snapshot.secondary)
        self.assertEqual(snapshot.secondary.used_percent, 8.0)

    def test_cursor_percent_fields_clamp_above_100(self) -> None:
        snapshot = normalize_cursor_snapshot(
            {
                "individualUsage": {
                    "plan": {
                        "totalPercentUsed": 150,
                        "autoPercentUsed": 120,
                    }
                },
            },
            None,
        )

        self.assertIsNotNone(snapshot.primary)
        self.assertEqual(snapshot.primary.used_percent, 100.0)
        self.assertIsNotNone(snapshot.secondary)
        self.assertEqual(snapshot.secondary.used_percent, 100.0)

    def test_cursor_ratio_fallback_stays_0_to_100(self) -> None:
        snapshot = normalize_cursor_snapshot(
            {
                "individualUsage": {
                    "plan": {
                        "used": 86,
                        "limit": 2000,
                    }
                },
            },
            None,
        )

        self.assertIsNotNone(snapshot.primary)
        self.assertEqual(snapshot.primary.used_percent, 4.3)

    def test_cli_row_does_not_round_fractional_api_percent_to_zero(self) -> None:
        snapshot = normalize_cursor_snapshot(
            {
                "individualUsage": {
                    "plan": {
                        "totalPercentUsed": 0.44,
                        "autoPercentUsed": 0.08,
                    }
                },
            },
            {"email": "user@example.com"},
        )

        row = _row(snapshot)

        self.assertEqual(row[3], "Total 56%")
        self.assertEqual(row[4], "44%")
        self.assertEqual(row[5], "Auto 92%")
        self.assertEqual(row[6], "8%")

    def test_cursor_primary_uses_auto_api_when_total_missing(self) -> None:
        snapshot = normalize_cursor_snapshot(
            {
                "individualUsage": {
                    "plan": {
                        "autoPercentUsed": 35,
                        "apiPercentUsed": 97,
                    }
                },
            },
            None,
        )

        self.assertIsNotNone(snapshot.primary)
        self.assertEqual(snapshot.primary.used_percent, 66)

    def test_cursor_overall_fallback(self) -> None:
        snapshot = normalize_cursor_snapshot(
            {
                "membershipType": "enterprise",
                "individualUsage": {
                    "overall": {
                        "used": 7384,
                        "limit": 10000,
                    }
                },
            },
            None,
        )

        self.assertIsNotNone(snapshot.primary)
        self.assertAlmostEqual(snapshot.primary.used_percent, 73.84)

    def test_cursor_pooled_fallback(self) -> None:
        snapshot = normalize_cursor_snapshot(
            {
                "membershipType": "enterprise",
                "teamUsage": {
                    "pooled": {
                        "used": 12_725_135,
                        "limit": 28_122_000,
                    }
                },
            },
            None,
        )

        self.assertIsNotNone(snapshot.primary)
        self.assertGreater(snapshot.primary.used_percent, 45.0)
        self.assertLess(snapshot.primary.used_percent, 45.5)

    def test_auth_me_failure_still_returns_cursor_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "cursor.toml"
            config_path.write_text('[cursor]\nenabled = true\ncookie_header = "redacted"\n', encoding="utf-8")
            with mock.patch.dict("os.environ", {"ZCOUNTER_CURSOR_CONFIG": str(config_path)}, clear=False):
                with mock.patch.object(
                    provider,
                    "fetch_usage_summary",
                    return_value={"individualUsage": {"plan": {"totalPercentUsed": 30.0}}},
                ):
                    with mock.patch.object(
                        provider,
                        "fetch_auth_me",
                        side_effect=CursorAPIError("cursor API request failed"),
                    ):
                        snapshot = provider.fetch_cursor_quota_if_configured()

        self.assertIsNotNone(snapshot)
        self.assertIsNone(snapshot.error)
        self.assertIsNone(snapshot.email)
        self.assertIsNotNone(snapshot.primary)
        self.assertEqual(snapshot.primary.used_percent, 30.0)

    def test_unauthorized_error_is_secret_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "cursor.toml"
            config_path.write_text('[cursor]\nenabled = true\ncookie_header = "redacted"\n', encoding="utf-8")
            with mock.patch.dict("os.environ", {"ZCOUNTER_CURSOR_CONFIG": str(config_path)}, clear=False):
                with mock.patch.object(
                    provider,
                    "fetch_usage_summary",
                    side_effect=CursorUnauthorizedError("cursor session is invalid or expired"),
                ):
                    snapshot = provider.fetch_cursor_quota_if_configured()

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.error, "cursor session is invalid or expired")
        self.assertNotIn("redacted", snapshot.error)

    def test_http_error_does_not_include_cookie(self) -> None:
        def fail(*args, **kwargs):
            raise urllib.error.HTTPError(
                usage_api.USAGE_SUMMARY_URL,
                500,
                "server rejected redacted",
                hdrs=None,
                fp=None,
            )

        with mock.patch.object(usage_api.urllib.request, "urlopen", side_effect=fail):
            with self.assertRaises(CursorAPIError) as raised:
                usage_api.fetch_usage_summary("redacted")

        self.assertNotIn("redacted", str(raised.exception))

    def test_parse_error_does_not_include_cookie(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"not json"

        with mock.patch.object(usage_api.urllib.request, "urlopen", return_value=Response()):
            with self.assertRaises(CursorShapeError) as raised:
                usage_api.fetch_usage_summary("redacted")

        self.assertNotIn("redacted", str(raised.exception))

    def test_config_missing_skips_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {"XDG_CONFIG_HOME": tmp}
            with mock.patch.dict("os.environ", env, clear=True):
                self.assertIsNone(provider.fetch_cursor_quota_if_configured())

    def test_explicit_missing_config_returns_secret_free_error_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "missing.toml"
            with mock.patch.dict("os.environ", {"ZCOUNTER_CURSOR_CONFIG": str(config_path)}, clear=True):
                snapshot = provider.fetch_cursor_quota_if_configured()

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.provider, "cursor")
        self.assertIn("cursor config path was not found", snapshot.error)
        self.assertNotIn("cookie_header", snapshot.error)

    def test_malformed_implicit_config_returns_secret_free_error_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "zcounter"
            config_dir.mkdir()
            config_path = config_dir / "cursor.toml"
            config_path.write_text('[cursor]\ncookie_header = "redacted"\ninvalid = [\n', encoding="utf-8")
            with mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp}, clear=True):
                snapshot = provider.fetch_cursor_quota_if_configured()

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.provider, "cursor")
        self.assertIn("cursor config is not valid TOML", snapshot.error)
        self.assertNotIn("redacted", snapshot.error)

    def test_enabled_false_skips_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "cursor.toml"
            config_path.write_text('[cursor]\nenabled = false\ncookie_header = "redacted"\n', encoding="utf-8")
            with mock.patch.dict("os.environ", {"ZCOUNTER_CURSOR_CONFIG": str(config_path)}, clear=False):
                self.assertIsNone(provider.fetch_cursor_quota_if_configured())


if __name__ == "__main__":
    unittest.main()
