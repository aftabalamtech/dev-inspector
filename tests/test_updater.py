import shutil
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devinspector import updater
from devinspector.core import CommandResult


@unittest.skipUnless(shutil.which("git"), "Git is required for updater integration tests")
class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "dev-inspector"
        self.repo.mkdir()
        self._local_git(["init", "-q", "-b", "main"])
        self._local_git(["config", "user.name", "Updater Test"])
        self._local_git(["config", "user.email", "updater-test@example.invalid"])
        (self.repo / "app.py").write_text("version = 1\n", encoding="utf-8")
        self._local_git(["add", "app.py"])
        self._local_git(["commit", "-q", "-m", "initial release"])
        self.base = self._local_git(["rev-parse", "HEAD"])
        self._local_git(["remote", "add", "origin", updater.EXPECTED_REMOTE_URL])
        self._local_git(["update-ref", "refs/remotes/origin/main", self.base])
        self._local_git(["branch", "--set-upstream-to=origin/main", "main"])
        self.upstream = self.base

    def tearDown(self):
        self.temp.cleanup()

    def _local_git(self, args):
        result = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True)
        if result.returncode:
            self.fail(f"Git test setup failed for {args!r}: {result.stderr}")
        return result.stdout.strip()

    def _commit_upstream(self, message="upstream improvement"):
        self._local_git(["checkout", "-q", "-b", "incoming"])
        (self.repo / "app.py").write_text("version = 2\n", encoding="utf-8")
        self._local_git(["commit", "-q", "-am", message])
        self.upstream = self._local_git(["rev-parse", "HEAD"])
        self._local_git(["checkout", "-q", "main"])
        self._local_git(["update-ref", "refs/remotes/origin/main", self.upstream])
        self._local_git(["branch", "-D", "incoming"])
        return self.upstream

    def _network_git(self, args, cwd, *, timeout=30, disable_hooks=False):
        if args[:2] == ["ls-remote", "--heads"]:
            return CommandResult(True, f"{self.upstream}\trefs/heads/main", "", 0)
        if args and args[0] == "fetch":
            return CommandResult(True, "", "", 0)
        return self._real_git(args, cwd, timeout=timeout, disable_hooks=disable_hooks)

    def setUp_network_patch(self):
        self._real_git = updater._git
        return patch.object(updater, "_git", side_effect=self._network_git)

    def test_normalize_expected_https_and_ssh_remotes(self):
        for value in (
            "https://github.com/aftabalamtech/dev-inspector.git",
            "https://github.com/aftabalamtech/dev-inspector",
            "git@github.com:aftabalamtech/dev-inspector.git",
            "ssh://git@github.com/aftabalamtech/dev-inspector.git",
        ):
            self.assertEqual(updater.normalize_github_repository(value), updater.EXPECTED_REPOSITORY)
        self.assertIsNone(updater.normalize_github_repository("https://example.com/aftabalamtech/dev-inspector.git"))

    def test_check_reports_already_up_to_date(self):
        with self.setUp_network_patch():
            state = updater.check_for_updates(self.repo)
        self.assertTrue(state["ok"])
        self.assertEqual(state["status"], "up_to_date")
        self.assertEqual(state["commits_behind"], 0)
        self.assertEqual(state["current_commit"], self.base)

    def test_current_version_comes_from_git_metadata(self):
        state = updater.current_version(self.repo)
        self.assertTrue(state["ok"])
        self.assertEqual(state["branch"], "main")
        self.assertEqual(state["current_commit"], self.base)
        self.assertEqual(state["remote_repository"], updater.EXPECTED_REPOSITORY)
        self.assertTrue(state["current_version"])

    def test_check_detects_available_update_and_commit_details(self):
        self._commit_upstream()
        with self.setUp_network_patch():
            state = updater.check_for_updates(self.repo)
        self.assertTrue(state["ok"])
        self.assertEqual(state["update_status"], "updates_available")
        self.assertEqual(state["commits_behind"], 1)
        self.assertEqual(state["latest_commit"], self.upstream)
        self.assertTrue(any("upstream improvement" in line for line in state["new_commits"]))
        self.assertIn("app.py", state["diff_stat"])

    def test_dirty_tracked_and_untracked_work_blocks_apply(self):
        self._commit_upstream()
        (self.repo / "app.py").write_text("my local work\n", encoding="utf-8")
        (self.repo / "notes.txt").write_text("untracked personal file\n", encoding="utf-8")
        with self.setUp_network_patch():
            state = updater.check_for_updates(self.repo)
            result = updater.apply_update(state)
        self.assertTrue(state["ok"])
        self.assertEqual(state["status"], "local_changes")
        self.assertTrue(any("app.py" in path for path in state["dirty_files"]))
        self.assertTrue(any("notes.txt" in path for path in state["dirty_files"]))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "local_changes")
        self.assertEqual((self.repo / "app.py").read_text(encoding="utf-8"), "my local work\n")
        self.assertTrue((self.repo / "notes.txt").exists())

    def test_wrong_remote_is_refused_before_network(self):
        self._local_git(["remote", "set-url", "origin", "https://github.com/someone-else/dev-inspector.git"])
        with patch.object(updater, "_git", wraps=updater._git) as git_spy:
            state = updater.check_for_updates(self.repo)
        self.assertFalse(state["ok"])
        self.assertEqual(state["status"], "remote_mismatch")
        self.assertIn("someone-else/dev-inspector", state["message"])
        self.assertNotIn("https://github.com/", state["message"])
        self.assertFalse(any(call.args[0][:1] == ["ls-remote"] for call in git_spy.call_args_list))

    def test_network_failure_is_reported_without_modifying_worktree(self):
        def fail_network(args, cwd, *, timeout=30, disable_hooks=False):
            if args and args[0] == "ls-remote":
                return CommandResult(True, "", "credential or network details", 128)
            return self._real_git(args, cwd, timeout=timeout, disable_hooks=disable_hooks)
        self._real_git = updater._git
        with patch.object(updater, "_git", side_effect=fail_network):
            state = updater.check_for_updates(self.repo)
        self.assertFalse(state["ok"])
        self.assertEqual(state["status"], "network_error")
        self.assertNotIn("credential or network details", state["message"])
        self.assertEqual(self._local_git(["rev-parse", "HEAD"]), self.base)

    def test_successful_apply_is_verified_fast_forward(self):
        self._commit_upstream()
        with self.setUp_network_patch():
            state = updater.check_for_updates(self.repo)
            result = updater.apply_update(state)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["current_commit"], self.upstream)
        self.assertEqual(self._local_git(["rev-parse", "HEAD"]), self.upstream)
        self.assertEqual((self.repo / "app.py").read_text(encoding="utf-8"), "version = 2\n")

    @unittest.skipIf(os.name == "nt", "POSIX hook fixture is not used on Windows")
    def test_update_does_not_execute_local_post_merge_hook(self):
        self._commit_upstream()
        marker = self.repo / "local-hook-was-run"
        hook = self.repo / ".git" / "hooks" / "post-merge"
        hook.write_text(f"#!/bin/sh\nprintf ran > '{marker}'\n", encoding="utf-8")
        hook.chmod(0o755)
        with self.setUp_network_patch():
            state = updater.check_for_updates(self.repo)
            result = updater.apply_update(state)
        self.assertTrue(result["ok"])
        self.assertFalse(marker.exists())

    def test_update_does_not_overwrite_ignored_user_file(self):
        self._local_git(["checkout", "-q", "-b", "incoming"])
        (self.repo / "personal-output.txt").write_text("upstream file\n", encoding="utf-8")
        self._local_git(["add", "personal-output.txt"])
        self._local_git(["commit", "-q", "-m", "add generated output path"])
        self.upstream = self._local_git(["rev-parse", "HEAD"])
        self._local_git(["checkout", "-q", "main"])
        self._local_git(["update-ref", "refs/remotes/origin/main", self.upstream])
        self._local_git(["branch", "-D", "incoming"])
        with (self.repo / ".git" / "info" / "exclude").open("a", encoding="utf-8") as exclude:
            exclude.write("\npersonal-output.txt\n")
        personal_file = self.repo / "personal-output.txt"
        personal_file.write_text("my ignored personal data\n", encoding="utf-8")
        with self.setUp_network_patch():
            state = updater.check_for_updates(self.repo)
            result = updater.apply_update(state)
        self.assertTrue(state["ok"])
        self.assertEqual(state["update_status"], "updates_available")
        self.assertFalse(result["ok"])
        self.assertEqual(personal_file.read_text(encoding="utf-8"), "my ignored personal data\n")

    def test_divergent_history_is_detected_and_not_applied(self):
        self._commit_upstream()
        self._local_git(["commit", "--allow-empty", "-q", "-m", "local-only commit"])
        local_head = self._local_git(["rev-parse", "HEAD"])
        with self.setUp_network_patch():
            state = updater.check_for_updates(self.repo)
            result = updater.apply_update(state)
        self.assertEqual(state["update_status"], "diverged")
        self.assertEqual(state["commits_behind"], 1)
        self.assertEqual(state["commits_ahead"], 1)
        self.assertFalse(result["ok"])
        self.assertEqual(self._local_git(["rev-parse", "HEAD"]), local_head)

    def test_non_git_install_is_explained_without_fetch(self):
        not_repo = Path(self.temp.name) / "archive-copy"
        not_repo.mkdir()
        state = updater.check_for_updates(not_repo)
        self.assertFalse(state["ok"])
        self.assertEqual(state["status"], "not_git_repository")
        self.assertIn("Git clone", state["message"])

    def test_commit_subject_redacts_common_token_forms(self):
        lines = updater._safe_log_lines("fix token=secret-value ghp_abcdefghijklmnopqrstuvwxyz0123456789")
        self.assertNotIn("secret-value", lines[0])
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz0123456789", lines[0])
        self.assertIn("[REDACTED]", lines[0])


if __name__ == "__main__":
    unittest.main()
