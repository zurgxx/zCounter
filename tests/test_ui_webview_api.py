from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

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


if __name__ == "__main__":
    unittest.main()
