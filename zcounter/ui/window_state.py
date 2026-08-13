from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, Thread
from typing import Any


WINDOW_STATE_ENV = "ZCOUNTER_WINDOW_STATE"
MIN_WINDOW_WIDTH = 200
MIN_WINDOW_HEIGHT = 100
MIN_VISIBLE_WIDTH = 80
MIN_VISIBLE_HEIGHT = 40
RELATIVE_POSITION_RENDERERS = {"gtkwebkit2", "qtwebkit", "qtwebengine", "cocoa"}


@dataclass(frozen=True)
class WindowGeometry:
    x: int
    y: int
    width: int
    height: int


def window_state_path() -> Path:
    override = os.environ.get(WINDOW_STATE_ENV)
    if override:
        return Path(override).expanduser()
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "zcounter" / "window.json"
    return Path.home() / ".config" / "zcounter" / "window.json"


def load_window_geometry(path: Path | None = None) -> WindowGeometry | None:
    state_path = path or window_state_path()
    try:
        with state_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return _geometry_from_mapping(data)


def save_window_geometry(geometry: WindowGeometry, path: Path | None = None) -> None:
    state_path = path or window_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "x": geometry.x,
        "y": geometry.y,
        "width": geometry.width,
        "height": geometry.height,
    }
    temporary_path: str | None = None
    try:
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{state_path.name}.",
            suffix=".tmp",
            dir=state_path.parent,
            text=True,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.write("\n")
        os.replace(temporary_path, state_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


def read_window_geometry(window) -> WindowGeometry:
    """Read all four values through pywebview's window geometry API."""
    return WindowGeometry(
        x=int(window.x),
        y=int(window.y),
        width=int(window.width),
        height=int(window.height),
    )


def restore_window_geometry(
    geometry: WindowGeometry | None,
    screens: list[Any],
    renderer: str | None,
) -> dict[str, Any]:
    """Build create_window arguments for a saved global geometry."""
    if geometry is None or not _valid_geometry(geometry) or not screens:
        return {}
    if not _is_visible_on_any_screen(geometry, screens):
        return {}

    screen = _screen_with_most_overlap(geometry, screens)
    args: dict[str, Any] = {
        "width": geometry.width,
        "height": geometry.height,
        "screen": screen,
    }
    if renderer in RELATIVE_POSITION_RENDERERS:
        args["x"] = geometry.x - int(screen.x)
        args["y"] = geometry.y - int(screen.y)
    else:
        args["x"] = geometry.x
        args["y"] = geometry.y
    return args


def _geometry_from_mapping(data: dict[str, Any]) -> WindowGeometry | None:
    values: list[int] = []
    for key in ("x", "y", "width", "height"):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        values.append(value)
    geometry = WindowGeometry(*values)
    return geometry if _valid_geometry(geometry) else None


def _valid_geometry(geometry: WindowGeometry) -> bool:
    return (
        geometry.width >= MIN_WINDOW_WIDTH
        and geometry.height >= MIN_WINDOW_HEIGHT
        and geometry.width <= 16_384
        and geometry.height <= 16_384
    )


def _is_visible_on_any_screen(geometry: WindowGeometry, screens: list[Any]) -> bool:
    return any(
        _intersection_size(geometry, screen)[0] >= min(MIN_VISIBLE_WIDTH, geometry.width)
        and _intersection_size(geometry, screen)[1] >= min(MIN_VISIBLE_HEIGHT, geometry.height)
        for screen in screens
    )


def _screen_with_most_overlap(geometry: WindowGeometry, screens: list[Any]) -> Any:
    return max(
        screens,
        key=lambda screen: (
            _intersection_size(geometry, screen)[0] * _intersection_size(geometry, screen)[1]
        ),
    )


def _intersection_size(geometry: WindowGeometry, screen: Any) -> tuple[int, int]:
    left = max(geometry.x, int(screen.x))
    top = max(geometry.y, int(screen.y))
    right = min(geometry.x + geometry.width, int(screen.x) + int(screen.width))
    bottom = min(geometry.y + geometry.height, int(screen.y) + int(screen.height))
    return max(0, right - left), max(0, bottom - top)


class WindowGeometryStore:
    def __init__(self, path: Path | None = None, initial: WindowGeometry | None = None) -> None:
        self.path = path or window_state_path()
        self._lock = Lock()
        self._values: dict[str, int | None] = {
            "x": initial.x if initial else None,
            "y": initial.y if initial else None,
            "width": initial.width if initial else None,
            "height": initial.height if initial else None,
        }

    def attach(self, window) -> None:
        window.events.moved += self._on_moved
        window.events.resized += self._on_resized
        # `closing` runs before the native window is destroyed. This is the
        # last reliable point at which the final geometry can be captured.
        window.events.closing += self._on_closing
        Thread(target=self._capture_when_shown, args=(window,), daemon=True).start()

    def _on_moved(self, window, *_args) -> None:
        self._capture(window)

    def _on_resized(self, window, *_args) -> None:
        self._capture(window)

    def _on_closing(self, window) -> None:
        # pywebview's public getters may wait for the GUI loop, while GTK is
        # currently executing the synchronous closing callback on that loop.
        # GTK exposes the same position/size API through the native window,
        # which lets us take the final snapshot without deadlocking.
        geometry = _read_native_geometry(window)
        if geometry is not None:
            self._store(geometry)
        else:
            self._save_if_complete()

    def _capture_when_shown(self, window) -> None:
        if window.events.shown.wait(10):
            self._capture(window)

    def _capture(self, window) -> None:
        try:
            geometry = read_window_geometry(window)
        except Exception:
            return
        self._store(geometry)

    def _store(self, geometry: WindowGeometry) -> None:
        with self._lock:
            self._values.update(
                x=geometry.x,
                y=geometry.y,
                width=geometry.width,
                height=geometry.height,
            )
            self._save_if_complete()

    def _save_if_complete(self) -> None:
        if not all(isinstance(value, int) for value in self._values.values()):
            return
        geometry = WindowGeometry(
            x=self._values["x"],
            y=self._values["y"],
            width=self._values["width"],
            height=self._values["height"],
        )
        try:
            save_window_geometry(geometry, self.path)
        except OSError:
            return


def _read_native_geometry(window) -> WindowGeometry | None:
    native = getattr(window, "native", None)
    if native is None:
        return None

    get_position = getattr(native, "get_position", None)
    get_size = getattr(native, "get_size", None)
    if callable(get_position) and callable(get_size):
        try:
            x, y = get_position()
            width, height = get_size()
            return WindowGeometry(int(x), int(y), int(width), int(height))
        except (TypeError, ValueError):
            return None
    return None
