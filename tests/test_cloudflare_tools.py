import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devinspector import cloudflare_tools as cf


class CloudflareToolTests(unittest.TestCase):
    def test_local_wrangler_uses_lockfile_manager_and_project_path(self):
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            (cwd / "package.json").write_text(json.dumps({"devDependencies": {"wrangler": "^3"}}))
            (cwd / "pnpm-lock.yaml").write_text("lockfileVersion: 6")
            binary = cwd / "node_modules" / ".bin" / "wrangler"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\n")
            with patch.object(cf.shutil, "which", side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None), patch.object(cf, "run", return_value=cf.CommandResult(True, "wrangler 3.0.0", "", 0)):
                record = cf.detect_cloudflare_tools(cwd)["wrangler"]
            self.assertTrue(record["installed"])
            self.assertEqual(record["install_method"], "project")
            self.assertEqual(record["package_manager"], "pnpm")
            self.assertEqual(record["path"], str(binary))
            update = cf.plan_update("wrangler", cwd)
            self.assertEqual(update["commands"], [["pnpm", "add", "--save-dev", "wrangler@latest"]])

    def test_global_wrangler_install_prefers_npm_when_no_project(self):
        with tempfile.TemporaryDirectory() as directory:
            def fake_run(args, **kwargs):
                if args[:3] == ["npm", "list", "--global"]:
                    return cf.CommandResult(True, '{"dependencies":{"wrangler":{"version":"4.0.0"}}}', "", 0)
                return cf.CommandResult(True, "wrangler 4.0.0", "", 0)
            with patch.object(cf.shutil, "which", side_effect=lambda name: "/usr/bin/wrangler" if name == "wrangler" else ("/usr/bin/npm" if name in {"npm", "node"} else None)), patch.object(cf, "run", side_effect=fake_run):
                record = cf.detect_cloudflare_tools(directory)["wrangler"]
                update = cf.plan_update("wrangler", directory)
            self.assertEqual(record["install_method"], "global")
            self.assertEqual(record["package_manager"], "npm")
            self.assertEqual(update["commands"], [["npm", "install", "--global", "wrangler@latest"]])

    def test_cf_install_requires_node_22_18(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(cf, "_node_cf_compatibility", return_value=("v22.13.0", False)):
                plan = cf._cf_install(Path(directory))
            self.assertFalse(plan["supported"])
            self.assertIn("22.18", plan["reason"])
            self.assertEqual(plan["commands"], [])

    def test_cf_global_npm_update_and_uninstall(self):
        record = {**cf._record(installed=True, version="cf 1.0.0", path="/usr/bin/cloudflare", method="global", manager="npm"),
                  "node_version": "v22.18.0", "runtime_compatible": True}
        with tempfile.TemporaryDirectory() as directory, patch.object(cf, "_cf_record", return_value=record):
            update = cf.plan_update("cf", directory)
            remove = cf.plan_uninstall("cf", directory)
        self.assertEqual(update["commands"], [["npm", "install", "--global", "cf@latest"]])
        self.assertEqual(remove["commands"], [["npm", "uninstall", "--global", "cf"]])

    def test_detect_global_cf_cli_and_node_runtime(self):
        def fake_which(name):
            return {"cloudflare": "/usr/bin/cloudflare", "npm": "/usr/bin/npm", "node": "/usr/bin/node"}.get(name)
        def fake_run(args, **kwargs):
            if args[0] == "npm":
                return cf.CommandResult(True, '{"dependencies":{"cf":{"version":"1.2.3"}}}', "", 0)
            if args[0] == "node":
                return cf.CommandResult(True, "v22.18.0", "", 0)
            return cf.CommandResult(True, "cf 1.2.3", "", 0)
        with tempfile.TemporaryDirectory() as directory, patch.object(cf.shutil, "which", side_effect=fake_which), patch.object(cf, "run", side_effect=fake_run):
            record = cf.detect_cloudflare_tools(directory)["cf"]
        self.assertTrue(record["installed"])
        self.assertEqual(record["install_method"], "global")
        self.assertEqual(record["package_manager"], "npm")
        self.assertEqual(record["node_version"], "v22.18.0")
        self.assertTrue(record["runtime_compatible"])

    def test_wrangler_install_uses_project_lockfile_manager(self):
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            (cwd / "package.json").write_text(json.dumps({"name": "worker"}))
            (cwd / "pnpm-lock.yaml").write_text("lockfileVersion: 6")
            with patch.object(cf.shutil, "which", side_effect=lambda name: "/usr/bin/" + name if name in {"node", "pnpm"} else None), patch.object(cf, "run", return_value=cf.CommandResult(False, error="not found")):
                plan = cf.plan_install("wrangler", cwd)
            self.assertTrue(plan["supported"])
            self.assertEqual(plan["commands"], [["pnpm", "add", "--save-dev", "wrangler@latest"]])

    def test_detected_apt_cloudflared_update_and_uninstall_match_manager(self):
        with tempfile.TemporaryDirectory() as directory:
            def fake_which(name):
                return "/usr/bin/" + name if name in {"cloudflared", "dpkg-query", "sudo", "apt-get"} else None
            def fake_run(args, **kwargs):
                if args[:2] == ["dpkg-query", "-S"]:
                    return cf.CommandResult(True, "cloudflared: /usr/bin/cloudflared", "", 0)
                return cf.CommandResult(True, "cloudflared version 2026.1", "", 0)
            with patch.object(cf.shutil, "which", side_effect=fake_which), patch.object(cf, "run", side_effect=fake_run):
                update = cf.plan_update("cloudflared", directory)
                remove = cf.plan_uninstall("cloudflared", directory)
            self.assertEqual(update["commands"], [["sudo", "apt-get", "update"], ["sudo", "apt-get", "install", "--only-upgrade", "-y", "cloudflared"]])
            self.assertEqual(remove["commands"], [["sudo", "apt-get", "remove", "-y", "cloudflared"]])

    def test_unknown_cloudflared_method_refuses_update_and_remove(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(cf.shutil, "which", side_effect=lambda name: "/opt/cloudflared" if name == "cloudflared" else None), patch.object(cf, "run", return_value=cf.CommandResult(True, "cloudflared version 2024", "", 0)):
                update = cf.plan_update("cloudflared", directory)
                remove = cf.plan_uninstall("cloudflared", directory)
            self.assertFalse(update["supported"])
            self.assertFalse(remove["supported"])
            self.assertEqual(update["commands"], [])
            self.assertIn("unknown", update["reason"])

    def test_cloudflared_linux_apt_plan_uses_official_urls_and_argv(self):
        with patch.object(cf.platform, "system", return_value="Linux"), patch.object(cf.platform, "machine", return_value="x86_64"), patch.object(cf.platform, "freedesktop_os_release", return_value={"ID": "ubuntu"}), patch.object(cf.shutil, "which", side_effect=lambda name: "/usr/bin/" + name if name in {"apt-get", "dpkg", "curl", "sudo"} else None), patch.object(cf.os.path, "exists", return_value=False):
            plan = cf._cloudflared_install()
        self.assertTrue(plan["supported"])
        self.assertTrue(any(cf.CLOUDFLARE_KEY_URL in command for command in plan["commands"][1]))
        self.assertIn(cf.CLOUDFLARE_APT_SOURCE, plan["command_input"][2])
        self.assertTrue(all(isinstance(command, list) for command in plan["commands"]))

    def test_cloudflared_android_has_no_arbitrary_download_plan(self):
        with patch.object(cf.platform, "system", return_value="Android"), patch.object(cf.platform, "machine", return_value="aarch64"):
            plan = cf._cloudflared_install()
        self.assertFalse(plan["supported"])
        self.assertEqual(plan["commands"], [])
        self.assertIn(cf.CLOUDFLARE_DOWNLOADS_URL, plan["reason"])

    def test_planning_does_not_execute_plan_commands(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(cf, "execute_plan") as execute:
            cf.plan_install("cloudflared", directory)
            cf.plan_update("cloudflared", directory)
            cf.plan_uninstall("cloudflared", directory)
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
