from __future__ import annotations

import logging
from pathlib import Path
from threading import Event, Thread
import time

from zcounter.ui.webview_api import WebviewAPI

WINDOW_WIDTH = 364
WINDOW_HEIGHT = 860
RESUME_POLL_SECONDS = 5
RESUME_GAP_SECONDS = 15

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


def run() -> None:
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

    api = WebviewAPI()
    window = webview.create_window(
        "zCounter",
        html_path.as_uri(),
        js_api=api,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        resizable=True,
        on_top=True,
    )
    if window is not None:
        _start_resume_monitor(window)
    webview.start()
