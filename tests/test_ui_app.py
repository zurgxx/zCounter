import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from zcounter.ui.app import UsageHistoryWindowController, _recover_window_after_resume


class FakeEvents:
    def __init__(self) -> None:
        self.calls = []


class FakeWindow:
    def __init__(self, on_top: bool) -> None:
        self.on_top = on_top
        self.events = FakeEvents()
        self.calls = []

    def restore(self) -> None:
        self.calls.append("restore")

    def run_js(self, script: str) -> None:
        self.calls.append(script)


class FakeEvent:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self) -> None:
        for handler in list(self.handlers):
            handler()


class HistoryFakeWindow:
    def __init__(self) -> None:
        self.calls = []
        self.fail_run_js = False
        self.events = SimpleNamespace(closed=FakeEvent())

    def restore(self) -> None:
        self.calls.append("restore")

    def show(self) -> None:
        self.calls.append("show")

    def run_js(self, script: str) -> None:
        self.calls.append(script)
        if self.fail_run_js:
            raise RuntimeError("page is not ready")


class FakeWebview:
    def __init__(self) -> None:
        self.windows = []
        self.create_args = []

    def create_window(self, *args, **kwargs):
        self.create_args.append((args, kwargs))
        window = HistoryFakeWindow()
        self.windows.append(window)
        return window


class UIAppTests(unittest.TestCase):
    def test_resume_reapplies_native_window_state_and_notifies_page(self) -> None:
        window = FakeWindow(on_top=True)

        _recover_window_after_resume(window)

        self.assertEqual(window.calls[0], "restore")
        self.assertEqual(window.calls[1:], [
            "window.dispatchEvent(new Event('zcounterresume'))",
        ])
        self.assertTrue(window.on_top)

    def test_resume_does_not_enable_keep_above_when_it_was_disabled(self) -> None:
        window = FakeWindow(on_top=False)

        _recover_window_after_resume(window)

        self.assertFalse(window.on_top)

    def test_history_window_reuses_single_window_and_reopens_after_close(self) -> None:
        webview = FakeWebview()
        html_path = Path("/tmp/usage_history.html")
        api_factory = mock.Mock(return_value=object())
        controller = UsageHistoryWindowController(webview, html_path, api_factory)

        self.assertTrue(controller.open())
        first_window = webview.windows[0]
        self.assertTrue(controller.open())
        self.assertEqual(len(webview.create_args), 1)
        self.assertEqual(first_window.calls, [
            "restore",
            "show",
            "window.dispatchEvent(new Event('usagehistoryrefresh'))",
        ])

        first_window.events.closed.fire()
        self.assertTrue(controller.open())
        self.assertEqual(len(webview.create_args), 2)
        self.assertEqual(webview.create_args[0][0][0], "Usage History")
        self.assertEqual(webview.create_args[0][0][1], html_path.as_uri())
        self.assertEqual(api_factory.call_count, 2)

    def test_history_window_is_reused_if_refresh_event_fails_while_page_loads(self) -> None:
        webview = FakeWebview()
        controller = UsageHistoryWindowController(webview, Path("/tmp/usage_history.html"))

        self.assertTrue(controller.open())
        webview.windows[0].fail_run_js = True
        with mock.patch("zcounter.ui.app.logger.debug") as debug:
            self.assertTrue(controller.open())

        self.assertEqual(len(webview.create_args), 1)
        debug.assert_called_once()


if __name__ == "__main__":
    unittest.main()
