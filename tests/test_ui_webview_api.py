from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from zcounter.models import QuotaSnapshot, RateWindow
from zcounter.ui.usage_history import read_usage_history
from zcounter.ui.webview_api import WebviewAPI
from tests.test_usage_log import _codex_snapshot, _cursor_snapshot


class WebviewAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.history_path = Path(self.temp_dir.name) / "usage-history.jsonl"
        env_patcher = mock.patch.dict(
            "os.environ",
            {
                "ZCOUNTER_USAGE_LOG": str(Path(self.temp_dir.name) / "usage.log"),
                "ZCOUNTER_USAGE_HISTORY": str(self.history_path),
            },
            clear=False,
        )
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

    def test_open_usage_history_delegates_and_handles_unavailable_window(self) -> None:
        api = WebviewAPI()
        self.assertFalse(api.open_usage_history())
        api.set_history_window_opener(lambda: True)
        self.assertTrue(api.open_usage_history())

        def fail_to_open() -> bool:
            raise RuntimeError("closed")

        api.set_history_window_opener(fail_to_open)
        with mock.patch("zcounter.ui.webview_api.logger.warning") as warning:
            self.assertFalse(api.open_usage_history())
        warning.assert_called_once()

    def test_refresh_appends_one_line_for_all_successful_visible_accounts(self) -> None:
        snapshots = [
            _codex_snapshot("codex-main@example.com"),
            _codex_snapshot("codex-sub@example.com", five_hour=88.0, weekly=63.0),
            _cursor_snapshot(),
        ]
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "usage.log"
            with mock.patch.dict("os.environ", {"ZCOUNTER_USAGE_LOG": str(log_path)}, clear=False):
                with mock.patch("zcounter.ui.webview_api.fetch_all_quotas", return_value=snapshots):
                    with mock.patch(
                        "zcounter.ui.webview_api.utc_now",
                        return_value=datetime(2026, 8, 20, 14, 5, 12, tzinfo=timezone.utc),
                    ):
                        api = WebviewAPI()
                        first = api.refresh()
                        second = api.refresh()

            self.assertFalse(first["busy"])
            self.assertFalse(second["busy"])
            self.assertEqual(len(log_path.read_text(encoding="utf-8").splitlines()), 2)

    def test_failed_account_is_logged_as_stale_without_previous_quota(self) -> None:
        successful = [
            _codex_snapshot("codex-main@example.com", five_hour=72.0),
            _codex_snapshot("codex-sub@example.com", five_hour=88.0),
            _cursor_snapshot(),
        ]
        failed = [
            _codex_snapshot("codex-main@example.com", five_hour=10.0),
            _codex_snapshot("codex-sub@example.com", five_hour=88.0, error="failed"),
            _cursor_snapshot(),
        ]
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "usage.log"
            with mock.patch.dict("os.environ", {"ZCOUNTER_USAGE_LOG": str(log_path)}, clear=False):
                with mock.patch("zcounter.ui.webview_api.fetch_all_quotas", side_effect=[successful, failed]):
                    with mock.patch(
                        "zcounter.ui.webview_api.utc_now",
                        return_value=datetime(2026, 8, 20, 14, 5, 12, tzinfo=timezone.utc),
                    ):
                        api = WebviewAPI()
                        api.refresh()
                        payload = api.refresh()

            log_lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(log_lines), 2)
            self.assertIn("codex-main:five_hour=10%", log_lines[1])
            self.assertIn("cursor:total=54%,first_party_models=37%", log_lines[1])
            self.assertNotIn("codex-sub", log_lines[1])
            self.assertEqual(payload["accounts"][1]["status"], "stale")

    def test_log_save_failure_does_not_fail_refresh(self) -> None:
        with mock.patch("zcounter.ui.webview_api.fetch_all_quotas", return_value=[_codex_snapshot("codex-main@example.com")]):
            with mock.patch("zcounter.ui.webview_api.append_usage_log", side_effect=OSError("read-only")):
                with mock.patch("zcounter.ui.webview_api.logger.warning"):
                    payload = WebviewAPI().refresh()

        self.assertFalse(payload["busy"])

    def test_merge_failure_does_not_append_usage_log(self) -> None:
        api = WebviewAPI()
        with mock.patch("zcounter.ui.webview_api.fetch_all_quotas", return_value=[_codex_snapshot("codex-main@example.com")]):
            with mock.patch.object(api._store, "merge", side_effect=RuntimeError("merge failed")) as merge:
                with mock.patch("zcounter.ui.webview_api.append_usage_log") as append:
                    with mock.patch("zcounter.ui.webview_api.append_usage_history") as append_history:
                        payload = api.refresh()

        self.assertFalse(payload["busy"])
        self.assertTrue(merge.called)
        append.assert_not_called()
        append_history.assert_not_called()

    def test_claude_stays_hidden_from_main_payload_but_is_written_to_history(self) -> None:
        claude = QuotaSnapshot(
            provider="claude",
            email="claude@example.com",
            plan="Pro",
            chatgpt_account_id=None,
            five_hour=None,
            weekly=None,
            primary=RateWindow(20.0, 80.0, None, 300, 18_000),
            primary_label="Session",
            provider_account_id="claude-account-uuid",
            source="claude-usage",
            updated_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        )
        with mock.patch(
            "zcounter.ui.webview_api.fetch_all_quotas",
            return_value=[claude, _codex_snapshot("codex-main@example.com")],
        ):
            payload = WebviewAPI().refresh()

        self.assertFalse(payload["busy"])
        self.assertNotIn("Claude", {account["provider"] for account in payload["accounts"]})
        observations = read_usage_history(self.history_path, Path(self.temp_dir.name) / "missing.log")
        claude_rows = [item for item in observations if item.provider == "claude"]
        self.assertEqual(len(claude_rows), 1)
        self.assertEqual(claude_rows[0].account_id, "claude-account-uuid")

    def test_history_append_failure_does_not_fail_main_refresh(self) -> None:
        with mock.patch(
            "zcounter.ui.webview_api.fetch_all_quotas",
            return_value=[_codex_snapshot("codex-main@example.com")],
        ):
            with mock.patch("zcounter.ui.webview_api.append_usage_history", side_effect=OSError("read-only")):
                with mock.patch("zcounter.ui.webview_api.logger.warning"):
                    payload = WebviewAPI().refresh()

        self.assertFalse(payload["busy"])

    def test_refresh_notifies_on_cursor_api_decrease_without_breaking_log(self) -> None:
        from zcounter.models import RateWindow

        def cursor_with_api(api_remaining: float) -> QuotaSnapshot:
            snapshot = _cursor_snapshot()
            snapshot = QuotaSnapshot(
                provider=snapshot.provider,
                email=snapshot.email,
                plan=snapshot.plan,
                chatgpt_account_id=snapshot.chatgpt_account_id,
                five_hour=snapshot.five_hour,
                weekly=snapshot.weekly,
                primary=snapshot.primary,
                secondary=snapshot.secondary,
                tertiary=RateWindow(100.0 - api_remaining, api_remaining, None, None),
                primary_label=snapshot.primary_label,
                secondary_label=snapshot.secondary_label,
                tertiary_label="API",
                provider_account_id=snapshot.provider_account_id,
                source=snapshot.source,
                updated_at=snapshot.updated_at,
            )
            return snapshot

        snapshots = [
            _codex_snapshot("codex-main@example.com"),
            cursor_with_api(100.0),
        ]
        decreased = [
            _codex_snapshot("codex-main@example.com"),
            cursor_with_api(99.0),
        ]
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "usage.log"
            with mock.patch.dict("os.environ", {"ZCOUNTER_USAGE_LOG": str(log_path)}, clear=False):
                with mock.patch("zcounter.ui.webview_api.fetch_all_quotas", side_effect=[snapshots, decreased]):
                    with mock.patch(
                        "zcounter.ui.webview_api.utc_now",
                        return_value=datetime(2026, 8, 20, 14, 5, 12, tzinfo=timezone.utc),
                    ):
                        with mock.patch("zcounter.notify.cursor_api.send_discord_message", return_value=True) as send:
                            api = WebviewAPI()
                            api.refresh()
                            payload = api.refresh()

                            self.assertFalse(payload["busy"])
                            self.assertEqual(len(log_path.read_text(encoding="utf-8").splitlines()), 2)
                            send.assert_called_once()

    def test_refresh_continues_when_discord_notify_fails(self) -> None:
        with mock.patch("zcounter.ui.webview_api.fetch_all_quotas", return_value=[_codex_snapshot("codex-main@example.com")]):
            with mock.patch(
                "zcounter.notify.cursor_api.maybe_notify_cursor_api_decrease",
                side_effect=RuntimeError("notify failed"),
            ):
                with mock.patch("zcounter.ui.webview_api.logger.warning"):
                    payload = WebviewAPI().refresh()

        self.assertFalse(payload["busy"])


if __name__ == "__main__":
    unittest.main()
