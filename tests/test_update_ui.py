import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from devinspector.main import show_main_menu
from devinspector import update_ui


class UpdateUiTests(unittest.TestCase):
    def test_main_menu_integrates_update_without_renumbering_existing_features(self):
        output = io.StringIO()
        with redirect_stdout(output):
            show_main_menu()
        text = output.getvalue()
        self.assertIn("[1] System Information", text)
        self.assertIn("[4] Cloudflare Toolkit", text)
        self.assertIn("[8] Diagnostic Report", text)
        self.assertIn("[9] Update Dev Inspector", text)
        self.assertIn("[0] Exit", text)

    def setUp(self):
        self.available = {
            "ok": True,
            "status": "updates_available",
            "update_status": "updates_available",
            "repo": "/tmp/dev-inspector",
            "branch": "main",
            "current_commit": "a" * 40,
            "current_version": "a" * 12,
            "latest_commit": "b" * 40,
            "latest_version": "b" * 12,
            "commits_behind": 1,
            "commits_ahead": 0,
            "upstream": "origin/main",
            "remote_repository": "aftabalamtech/dev-inspector",
            "dirty_files": [],
            "new_commits": ["bbbbbbb improve diagnostics"],
            "diff_stat": "1 file changed",
            "message": "Updates available",
        }

    def test_cancel_does_not_apply_update(self):
        output = io.StringIO()
        with patch.object(update_ui.updater, "check_for_updates", return_value=self.available), \
             patch.object(update_ui.updater, "apply_update") as apply, \
             patch("builtins.input", side_effect=["1", "n", "0"]), \
             redirect_stdout(output):
            update_ui.update_manager_menu()
        apply.assert_not_called()
        self.assertIn("Update cancelled", output.getvalue())

    def test_confirmed_update_calls_verified_apply(self):
        output = io.StringIO()
        success = {
            "ok": True,
            "status": "updated",
            "previous_commit": "a" * 40,
            "current_commit": "b" * 40,
            "branch": "main",
            "message": "Fast-forward complete",
        }
        with patch.object(update_ui.updater, "check_for_updates", return_value=self.available), \
             patch.object(update_ui.updater, "apply_update", return_value=success) as apply, \
             patch("builtins.input", side_effect=["1", "y", "0"]), \
             redirect_stdout(output):
            update_ui.update_manager_menu()
        apply.assert_called_once_with(self.available)
        self.assertIn("Restart Dev Inspector", output.getvalue())

    def test_menu_zero_returns_to_main_menu(self):
        output = io.StringIO()
        with patch("builtins.input", side_effect=["0"]), redirect_stdout(output):
            update_ui.update_manager_menu()
        self.assertIn("DEV INSPECTOR UPDATE MANAGER", output.getvalue())


if __name__ == "__main__":
    unittest.main()
