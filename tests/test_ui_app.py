import unittest

from zcounter.ui.app import _recover_window_after_resume


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


if __name__ == "__main__":
    unittest.main()
