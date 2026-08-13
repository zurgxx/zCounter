import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from zcounter.ui.window_state import (
    WindowGeometry,
    WindowGeometryStore,
    load_window_geometry,
    restore_window_geometry,
    save_window_geometry,
)


def _screen(x: int, y: int, width: int, height: int):
    return SimpleNamespace(x=x, y=y, width=width, height=height)


class WindowStateTests(unittest.TestCase):
    def test_move_event_uses_current_window_geometry_not_event_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "window.json"
            store = WindowGeometryStore(path)
            window = SimpleNamespace(x=321, y=222, width=364, height=860)

            store._on_moved(window, 0, 0)

            self.assertEqual(
                load_window_geometry(path),
                WindowGeometry(321, 222, 364, 860),
            )

    def test_closing_captures_final_native_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "window.json"
            store = WindowGeometryStore(path, WindowGeometry(0, 0, 364, 860))
            native = SimpleNamespace(
                get_position=lambda: (123, 456),
                get_size=lambda: (364, 812),
            )
            window = SimpleNamespace(native=native, x=0, y=0, width=364, height=860)

            store._on_closing(window)

            self.assertEqual(
                load_window_geometry(path),
                WindowGeometry(123, 456, 364, 812),
            )

    def test_geometry_round_trips_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "window.json"
            geometry = WindowGeometry(-1920, 120, 364, 860)

            save_window_geometry(geometry, path)

            self.assertEqual(load_window_geometry(path), geometry)

    def test_relative_renderer_restores_on_the_saved_monitor(self) -> None:
        geometry = WindowGeometry(1920 + 80, 120, 364, 860)
        screens = [_screen(0, 0, 1920, 1080), _screen(1920, 0, 2560, 1440)]

        restored = restore_window_geometry(geometry, screens, "gtkwebkit2")

        self.assertEqual(restored["x"], 80)
        self.assertEqual(restored["y"], 120)
        self.assertIs(restored["screen"], screens[1])
        self.assertEqual(restored["width"], 364)
        self.assertEqual(restored["height"], 860)

    def test_absolute_renderer_keeps_global_coordinates(self) -> None:
        geometry = WindowGeometry(-1920 + 80, 120, 364, 860)
        screens = [_screen(0, 0, 1920, 1080), _screen(-1920, 0, 1920, 1080)]

        restored = restore_window_geometry(geometry, screens, "winforms")

        self.assertEqual(restored["x"], -1840)
        self.assertEqual(restored["y"], 120)
        self.assertIs(restored["screen"], screens[1])

    def test_offline_monitor_falls_back_to_default_geometry(self) -> None:
        geometry = WindowGeometry(3840, 120, 364, 860)
        screens = [_screen(0, 0, 1920, 1080)]

        self.assertEqual(restore_window_geometry(geometry, screens, "gtkwebkit2"), {})

    def test_malformed_state_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "window.json"
            path.write_text(json.dumps({"x": 10, "y": 20, "width": "364", "height": 860}))

            self.assertIsNone(load_window_geometry(path))


if __name__ == "__main__":
    unittest.main()
