import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devinspector import cloudflare_ui as ui


class CloudflareUiSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tools = {
            "wrangler": {"installed": False, "version": None, "path": None, "install_method": "unknown", "package_manager": None},
            "cloudflared": {"installed": True, "version": "cloudflared 2026.1", "path": "/usr/bin/cloudflared", "install_method": "apt", "package_manager": None},
        }
        self.plan = {"title": "Test operation", "commands": [["sudo", "apt-get", "remove", "cloudflared"]],
                     "display_commands": ["sudo apt-get remove cloudflared"], "supported": True,
                     "reason": "test", "warnings": []}

    def test_install_cancellation_does_not_execute_plan(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(ui, "_show_tools", return_value=self.tools), \
             patch.object(ui, "plan_install", return_value=self.plan), \
             patch.object(ui, "execute_plan") as execute, \
             patch("builtins.input", side_effect=["1", "1", "n", "0", "0"]), \
             contextlib.redirect_stdout(io.StringIO()):
            ui.cloudflare_menu(Path(directory))
        execute.assert_not_called()

    def test_uninstall_cancellation_does_not_execute_plan(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(ui, "_show_tools", return_value=self.tools), \
             patch.object(ui, "plan_uninstall", return_value=self.plan), \
             patch.object(ui, "execute_plan") as execute, \
             patch("builtins.input", side_effect=["1", "n", "2"]), \
             contextlib.redirect_stdout(io.StringIO()):
            ui._update_or_remove_menu(Path(directory), uninstall=True)
        execute.assert_not_called()

    def test_quick_tunnel_rejects_non_loopback_and_invalid_ports(self):
        self.assertEqual(ui._loopback_url("https://example.com")[0], None)
        self.assertIsNotNone(ui._loopback_url("https://example.com")[1])
        self.assertEqual(ui._loopback_url("99999")[0], None)
        self.assertIsNotNone(ui._loopback_url("99999")[1])
        self.assertEqual(ui._loopback_url("8080"), ("http://127.0.0.1:8080", None))


if __name__ == "__main__":
    unittest.main()
