from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from zcounter.models import QuotaSnapshot
from zcounter.ui.webview_api import WebviewAPI
from tests.test_usage_log import _codex_snapshot, _cursor_snapshot


class WebviewAPITests(unittest.TestCase):
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

    def test_failed_account_does_not_append_or_use_previous_value(self) -> None:
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

            self.assertEqual(len(log_path.read_text(encoding="utf-8").splitlines()), 1)
            self.assertIn("codex-sub:five_hour=88%", log_path.read_text(encoding="utf-8"))
            self.assertNotIn("codex-main:five_hour=10%", log_path.read_text(encoding="utf-8"))
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
                    payload = api.refresh()

        self.assertFalse(payload["busy"])
        self.assertTrue(merge.called)
        append.assert_not_called()

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
