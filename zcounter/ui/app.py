from __future__ import annotations

import logging
import os
from pathlib import Path
from threading import Event, Lock, Thread
import time
from typing import Any, Callable

from zcounter.ui.usage_history import UsageHistoryAPI
from zcounter.ui.webview_api import WebviewAPI
from zcounter.ui.window_state import (
    WindowGeometryStore,
    load_window_geometry,
    restore_window_geometry,
    window_state_path,
)

WINDOW_WIDTH = 364
WINDOW_HEIGHT = 860
RESUME_POLL_SECONDS = 5
RESUME_GAP_SECONDS = 15
HISTORY_WINDOW_WIDTH = 1120
HISTORY_WINDOW_HEIGHT = 820

logger = logging.getLogger(__name__)


def _system_uptime() -> float:
    """Return an elapsed clock that includes time spent suspended when possible."""
    boot_clock = getattr(time, "CLOCK_BOOTTIME", None)
    if boot_clock is not None:
        return time.clock_gettime(boot_clock)
    return time.monotonic()


def _recover_window_after_resume(window) -> None:
    # GTK can retain stale focus/keep-above state after resume.
    # Re-applying these properties is harmless during normal use and
    # makes the native close button responsive again on affected WMs.
    window.restore()
    was_on_top = window.on_top
    window.on_top = False
    if was_on_top:
        window.on_top = True
    window.run_js("window.dispatchEvent(new Event('zcounterresume'))")


def _start_resume_monitor(window) -> Event:
    """Re-arm the GTK window and page after a system suspend/resume cycle."""
    stop = Event()

    def stop_monitor(*_args) -> None:
        stop.set()

    window.events.closed += stop_monitor

    def monitor() -> None:
        previous = _system_uptime()
        while not stop.wait(RESUME_POLL_SECONDS):
            current = _system_uptime()
            gap = current - previous
            previous = current
            if gap < RESUME_GAP_SECONDS:
                continue

            try:
                _recover_window_after_resume(window)
            except Exception:
                # The window may have been closed while the monitor was waking.
                logger.debug("failed to recover the WebView after resume", exc_info=True)

    Thread(target=monitor, name="zcounter-resume-monitor", daemon=True).start()
    return stop


class UsageHistoryWindowController:
    """履歴ウィンドウを1つだけ維持し、閉じた後は再度開けるようにする。"""

    def __init__(
        self,
        webview_module: Any,
        html_path: Path,
        api_factory: Callable[[], UsageHistoryAPI] = UsageHistoryAPI,
    ) -> None:
        self._webview = webview_module
        self._html_path = html_path
        self._api_factory = api_factory
        self._lock = Lock()
        self._window = None

    def open(self) -> bool:
        with self._lock:
            if self._window is not None:
                try:
                    self._window.restore()
                    self._window.show()
                except Exception:
                    # A native window can disappear before its closed event runs.
                    self._window = None
                else:
                    try:
                        self._window.run_js(
                            "window.dispatchEvent(new Event('usagehistoryrefresh'))"
                        )
                    except Exception:
                        # A page that is still loading will refresh on pywebviewready.
                        logger.debug("failed to refresh existing usage history window", exc_info=True)
                    return True

            window = self._webview.create_window(
                "Usage History",
                self._html_path.as_uri(),
                js_api=self._api_factory(),
                width=HISTORY_WINDOW_WIDTH,
                height=HISTORY_WINDOW_HEIGHT,
                resizable=True,
                on_top=False,
            )
            if window is None:
                return False

            self._window = window
            window.events.closed += lambda *_args, closed=window: self._clear_if_current(closed)
            return True

    def _clear_if_current(self, closed_window) -> None:
        with self._lock:
            if self._window is closed_window:
                self._window = None


def run() -> None:
    # Wayland does not expose reliable global window coordinates to clients.
    # Use X11/XWayland for this process so multi-monitor geometry can be saved.
    os.environ["GDK_BACKEND"] = "x11"
    try:
        import webview
    except ImportError as exc:
        raise SystemExit(
            "pywebview is required for the desktop UI. "
            "Install it with: python3 -m pip install -e '.[desktop]'"
        ) from exc

    html_path = Path(__file__).with_name("assets") / "index.html"
    if not html_path.is_file():
        raise SystemExit(f"UI asset was not found: {html_path}")
    history_html_path = Path(__file__).with_name("assets") / "usage_history.html"
    if not history_html_path.is_file():
        raise SystemExit(f"UI asset was not found: {history_html_path}")

    api = WebviewAPI()
    history_windows = UsageHistoryWindowController(webview, history_html_path)
    api.set_history_window_opener(history_windows.open)
    saved_geometry = load_window_geometry()
    restored_args = {}
    if saved_geometry is not None:
        try:
            screens = webview.screens
            restored_args = restore_window_geometry(saved_geometry, screens, webview.renderer)
        except Exception:
            logger.debug("failed to inspect screens for window restore", exc_info=True)

    window_args = {
        "width": WINDOW_WIDTH,
        "height": WINDOW_HEIGHT,
        "resizable": True,
        "on_top": True,
    }
    window_args.update(restored_args)
    window = webview.create_window(
        "zCounter",
        html_path.as_uri(),
        js_api=api,
        **window_args,
    )
    if window is not None:
        WindowGeometryStore(window_state_path(), saved_geometry).attach(window)
        _start_resume_monitor(window)
    webview.start()
