import io
import os
import unittest
from unittest.mock import patch

from devinspector.ui import color_supported, render, selection_menu


class TerminalUiTests(unittest.TestCase):
    def test_plain_text_for_non_tty_stream(self):
        stream = io.StringIO()
        self.assertFalse(color_supported(stream))
        self.assertNotIn("\033[", render("Example", {"status": "installed"}, stream=stream))

    @patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True)
    def test_color_enabled_for_tty(self):
        stream = io.StringIO()
        stream.isatty = lambda: True
        self.assertTrue(color_supported(stream))
        self.assertIn("\033[", render("Example", {"status": "installed"}, stream=stream))

    @patch.dict(os.environ, {"NO_COLOR": "1", "TERM": "xterm-256color"}, clear=True)
    def test_no_color_environment_variable_disables_ansi(self):
        stream = io.StringIO()
        stream.isatty = lambda: True
        self.assertFalse(color_supported(stream))
        self.assertNotIn("\033[", render("Example", {"status": "missing"}, stream=stream))

    def test_menu_numbers_and_status_are_readable_in_plain_mode(self):
        stream = io.StringIO()
        output = selection_menu("Actions", {"1": "Run check", "0": "Back"}, stream=stream)
        self.assertIn("[1] Run check", output)
        self.assertIn("[0] Back", output)
        self.assertIn("[NOT FOUND]", render("Tools", {"status": "missing"}, stream=stream))


if __name__ == "__main__":
    unittest.main()
