from __future__ import annotations

from pathlib import Path

from zcounter.ui.webview_api import WebviewAPI

WINDOW_WIDTH = 364
WINDOW_HEIGHT = 860


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
    webview.create_window(
        "zCounter",
        html_path.as_uri(),
        js_api=api,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        resizable=True,
        on_top=True,
    )
    webview.start()
