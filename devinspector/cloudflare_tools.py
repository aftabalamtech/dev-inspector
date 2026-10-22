"""Safe detection and confirmation-gated plans for Cloudflare CLI tools.

The functions in this module inspect the current machine and return plans; they
never install, update, or remove anything unless :func:`execute_plan` is called
with ``confirmed=True`` by the caller.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable, Sequence

from .core import CommandResult, run


CLOUDFLARE_DOWNLOADS_URL = "https://developers.cloudflare.com/tunnel/downloads/"
CLOUDFLARE_PACKAGE_URL = "https://pkg.cloudflare.com/"
CLOUDFLARE_KEY_URL = "https://pkg.cloudflare.com/cloudflare-main.gpg"
CLOUDFLARE_APT_SOURCE = "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main"
CLOUDFLARE_RPM_REPO = "https://pkg.cloudflare.com/cloudflared.repo"


def _path(cwd: Path | str) -> Path:
    return Path(cwd).expanduser()


def _available(command: str) -> bool:
    return shutil.which(command) is not None


def _first_line(value: str | None) -> str | None:
    if not value:
        return None
    for line in value.splitlines():
        line = line.strip()
        if line:
            return line[:300]
    return None


def _version(executable: str | Path, cwd: Path) -> str | None:
    """Read only a tool's version line; never include arbitrary command output."""
    if Path(executable).suffix.lower() in {".cmd", ".bat"}:
        stem = Path(executable).stem.lower()
        package_name = "cf" if stem in {"cf", "cloudflare"} else "wrangler"
        package_file = cwd / "node_modules" / package_name / "package.json"
        try:
            package = json.loads(package_file.read_text(encoding="utf-8"))
            version = package.get("version") if isinstance(package, dict) else None
            if version:
                return f"{package_name} {str(version)[:100]}"
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    result = run([str(executable), "--version"], cwd=str(cwd))
    if result.returncode == 0:
        return _first_line(result.stdout)
    return _first_line(result.stderr) if result.stderr and "version" in result.stderr.lower() else None


def _package_json(cwd: Path) -> dict[str, Any] | None:
    package_file = cwd / "package.json"
    if not package_file.is_file():
        return None
    try:
        data = json.loads(package_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _lock_manager(cwd: Path) -> str | None:
    # Lockfile order is deliberate: a project should be changed by its own
    # package manager, not by whichever one happens to be globally installed.
    for filename, manager in (
        ("package-lock.json", "npm"),
        ("npm-shrinkwrap.json", "npm"),
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lock", "bun"),
        ("bun.lockb", "bun"),
    ):
        if (cwd / filename).is_file():
            return manager
    return None


def _node_manager(cwd: Path, preferred: str | None = None) -> str | None:
    if preferred:
        return preferred if _available(preferred) else None
    candidates = [preferred] if preferred else []
    candidates += ["npm", "pnpm", "yarn", "bun"]
    seen: set[str] = set()
    for manager in candidates:
        if manager and manager not in seen:
            seen.add(manager)
            if _available(manager):
                return manager
    return None


def _local_wrangler(cwd: Path) -> Path | None:
    package = _package_json(cwd)
    if not package:
        return None
    dependencies: dict[str, Any] = {}
    for section in ("dependencies", "devDependencies"):
        value = package.get(section)
        if isinstance(value, dict):
            dependencies.update(value)
    if "wrangler" not in dependencies:
        return None
    # npm's bin shim has no extension on Unix.  The cmd variant keeps the
    # detector useful on Windows without changing the public path semantics.
    for candidate in (cwd / "node_modules" / ".bin" / "wrangler", cwd / "node_modules" / ".bin" / "wrangler.cmd"):
        if candidate.is_file():
            return candidate
    return None


def _local_cf(cwd: Path) -> Path | None:
    package = _package_json(cwd)
    if not package:
        return None
    dependencies: dict[str, Any] = {}
    for section in ("dependencies", "devDependencies"):
        value = package.get(section)
        if isinstance(value, dict):
            dependencies.update(value)
    if "cf" not in dependencies:
        return None
    for name in ("cf", "cloudflare"):
        for candidate in (cwd / "node_modules" / ".bin" / name, cwd / "node_modules" / ".bin" / f"{name}.cmd"):
            if candidate.is_file():
                return candidate
    return None


def _node_cf_compatibility() -> tuple[str | None, bool]:
    result = run(["node", "--version"])
    version = _first_line(result.stdout or result.stderr) if result.returncode == 0 else None
    match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", version or "")
    compatible = bool(match and tuple(map(int, match.groups())) >= (22, 18, 0))
    return version, compatible


def _cf_global_manager() -> str | None:
    if _available("npm"):
        result = _command(("npm", "list", "--global", "--depth=0", "--json"))
        if result.returncode == 0:
            try:
                dependencies = json.loads(result.stdout or "{}").get("dependencies", {})
                if isinstance(dependencies, dict) and "cf" in dependencies:
                    return "npm"
            except (TypeError, json.JSONDecodeError):
                pass
    if _available("pnpm"):
        result = _command(("pnpm", "list", "--global", "--depth=0", "--json"))
        if result.returncode == 0 and re.search(r'"(?:cf|name)"\s*:', result.stdout or "") and '"cf"' in (result.stdout or ""):
            return "pnpm"
    if _available("yarn") and _yarn_global_supported():
        result = _command(("yarn", "global", "list", "--json"))
        if result.returncode == 0 and re.search(r"(?:^|[\s\"'])cf@", result.stdout or ""):
            return "yarn"
    if _available("bun"):
        result = _command(("bun", "pm", "ls", "-g"))
        if result.returncode == 0 and re.search(r"(?:^|[\s\"'])cf@", result.stdout or ""):
            return "bun"
    return None


def _yarn_global_supported() -> bool:
    """Yarn's documented global-install syntax applies to Yarn Classic (v1)."""
    result = _command(("yarn", "--version"))
    match = re.match(r"\s*(\d+)", result.stdout or result.stderr or "")
    return bool(result.returncode == 0 and match and int(match.group(1)) == 1)


def _support(method: str, *, manager: str | None = None) -> tuple[bool, bool]:
    if method in {"homebrew", "apt", "dnf", "yum", "pacman"}:
        return True, True
    if method in {"project", "global"}:
        return manager is not None, manager is not None
    return False, False


def _record(*, installed: bool, version: str | None, path: str | None, method: str, manager: str | None = None) -> dict[str, Any]:
    update, remove = _support(method, manager=manager)
    # Keep both spellings useful to existing callers while making the primary
    # fields explicit and consistent for dynamic tool records.
    return {
        "installed": installed,
        "version": version,
        "path": path,
        "install_method": method,
        "package_manager": manager,
        "update_supported": update,
        "remove_supported": remove,
        "supports_update": update,
        "supports_uninstall": remove,
    }


def _wrangler_record(cwd: Path) -> dict[str, Any]:
    local = _local_wrangler(cwd)
    if local is not None:
        manager = _node_manager(cwd, _lock_manager(cwd))
        return _record(installed=True, version=_version(local, cwd), path=str(local), method="project", manager=manager)
    executable = shutil.which("wrangler")
    if executable:
        manager = None
        if _available("npm"):
            result = _command(("npm", "list", "--global", "--depth=0", "--json"))
            if result.returncode == 0:
                try:
                    packages = json.loads(result.stdout or "{}").get("dependencies", {})
                    if isinstance(packages, dict) and "wrangler" in packages:
                        manager = "npm"
                except (TypeError, json.JSONDecodeError):
                    pass
        return _record(installed=True, version=_version(executable, cwd), path=str(executable), method="global", manager=manager)
    return _record(installed=False, version=None, path=None, method="unknown")


def _cf_record(cwd: Path) -> dict[str, Any]:
    local = _local_cf(cwd)
    if local is not None:
        manager = _node_manager(cwd, _lock_manager(cwd))
        version = _version(local, cwd)
        method = "project"
        path = str(local)
    else:
        executable = shutil.which("cloudflare") or shutil.which("cf")
        if not executable:
            version, method, path, manager = None, "unknown", None, None
        else:
            version = _version(executable, cwd)
            manager = _cf_global_manager()
            method = "global" if manager else "unknown"
            path = executable
    node_version, compatible = _node_cf_compatibility()
    return {**_record(installed=path is not None, version=version, path=path, method=method, manager=manager),
            "node_version": node_version or "not installed", "runtime_compatible": compatible}


def _command(args: Sequence[str]) -> CommandResult:
    """Run a metadata query without a shell, returning a safe command result."""
    return run(list(args))


def _cloudflared_method(executable: str) -> str:
    # Homebrew ownership is checked first because brew installs commonly live
    # in /usr/local or /opt/homebrew and otherwise resemble manual binaries.
    if _available("brew"):
        for args in (("brew", "list", "--versions", "cloudflared"), ("brew", "--prefix", "cloudflared")):
            result = _command(args)
            if result.returncode == 0 and (result.stdout or "cloudflared" in (result.stderr or "").lower()):
                return "homebrew"

    dpkg_query = "dpkg-query" if _available("dpkg-query") else ("dpkg" if _available("dpkg") else None)
    if dpkg_query:
        result = _command((dpkg_query, "-S", executable))
        if result.returncode == 0 and "cloudflared" in (result.stdout or "").lower():
            return "apt"
        status_args = (dpkg_query, "-W", "-f=${Status}", "cloudflared") if dpkg_query == "dpkg-query" else (dpkg_query, "-s", "cloudflared")
        result = _command(status_args)
        if result.returncode == 0 and "installed" in (result.stdout or "").lower():
            return "apt"

    if _available("rpm"):
        result = _command(("rpm", "-qf", executable))
        if result.returncode == 0 and "cloudflared" in (result.stdout or "").lower():
            if _available("dnf"):
                return "dnf"
            if _available("yum"):
                return "yum"
    if _available("pacman"):
        result = _command(("pacman", "-Qo", executable))
        if result.returncode == 0 and "cloudflared" in (result.stdout or "").lower():
            return "pacman"
    return "unknown"


def _cloudflared_record(cwd: Path) -> dict[str, Any]:
    executable = shutil.which("cloudflared")
    if not executable:
        return _record(installed=False, version=None, path=None, method="unknown")
    method = _cloudflared_method(executable)
    return _record(installed=True, version=_version(executable, cwd), path=str(executable), method=method)


def detect_cloudflare_tools(cwd: Path | str) -> dict[str, dict[str, Any]]:
    """Detect Wrangler and cloudflared without reading environment values."""
    directory = _path(cwd)
    return {"cf": _cf_record(directory), "wrangler": _wrangler_record(directory), "cloudflared": _cloudflared_record(directory)}


def _plan(title: str, commands: Iterable[Sequence[str]], supported: bool, reason: str, warnings: Iterable[str] = ()) -> dict[str, Any]:
    argv = [list(command) for command in commands]
    result: dict[str, Any] = {
        "title": title,
        "commands": argv,
        "display_commands": [" ".join(_quote_arg(part) for part in command) for command in argv],
        "supported": bool(supported),
        "reason": reason,
    }
    warning_list = list(warnings)
    if warning_list:
        result["warnings"] = warning_list
    return result


def _quote_arg(value: str) -> str:
    # Display-only quoting; command execution still uses argv and never a shell.
    if value and all(character.isalnum() or character in "._/:=@+-" for character in value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def _wrangler_install(cwd: Path) -> dict[str, Any]:
    package = _package_json(cwd)
    node = _available("node")
    npm = _available("npm")
    if package is not None and node:
        manager = _node_manager(cwd, _lock_manager(cwd))
        if manager == "npm":
            command = ["npm", "install", "--save-dev", "wrangler@latest"]
        elif manager == "pnpm":
            command = ["pnpm", "add", "--save-dev", "wrangler@latest"]
        elif manager == "yarn":
            command = ["yarn", "add", "--dev", "wrangler@latest"]
        elif manager == "bun":
            command = ["bun", "add", "--dev", "wrangler@latest"]
        else:
            return _plan("Install Wrangler", [], False, "A package.json exists, but no supported Node package manager is available.")
        return _plan(
            "Install Wrangler for this project",
            [command],
            True,
            "Official per-project Wrangler installation; the detected project package manager and lockfile are preferred.",
        )
    if package is not None and not node:
        return _plan("Install Wrangler", [], False, "A package.json exists, but Node.js is required for the local project installation.")
    if npm and node:
        return _plan("Install Wrangler globally", [["npm", "install", "--global", "wrangler@latest"]], True, "No package.json was found; this is the global npm fallback. Cloudflare recommends installing Wrangler locally per project.", warnings=["Global installation is a convenience fallback; prefer a project-local Wrangler install when possible."])
    return _plan("Install Wrangler", [], False, "Wrangler installation requires Node.js and npm, or a project package.json with those tools available.")


def _cf_install(cwd: Path) -> dict[str, Any]:
    node_version, compatible = _node_cf_compatibility()
    if not compatible:
        return _plan("Install Cloudflare CLI (cf)", [], False,
                     f"Cloudflare cf requires Node.js 22.18 or later; detected {node_version or 'no Node.js'}. Install a supported Node.js release first.")
    package = _package_json(cwd)
    project_manager = _node_manager(cwd, _lock_manager(cwd)) if package is not None else None
    if project_manager:
        commands = {
            "npm": ["npm", "install", "--save-dev", "cf@latest"],
            "pnpm": ["pnpm", "add", "--save-dev", "cf@latest"],
            "yarn": ["yarn", "add", "--dev", "cf@latest"],
            "bun": ["bun", "add", "--dev", "cf@latest"],
        }
        return _plan("Install Cloudflare CLI (cf) for this project", [commands[project_manager]], True,
                     f"Add cf as a project development dependency with the detected {project_manager} package manager.",
                     warnings=["Cloudflare documents global installation as the default. Bun is not supported as the CLI runtime; use supported Node.js."])
    manager = next((name for name in ("npm", "yarn", "pnpm", "bun")
                    if _available(name) and (name != "yarn" or _yarn_global_supported())), None)
    if manager is None:
        return _plan("Install Cloudflare CLI (cf)", [], False, "Install Node.js 22.18+ and a supported global package manager (npm, Yarn Classic, pnpm, or Bun). Yarn Berry does not support the documented yarn global command.")
    commands = {
        "npm": ["npm", "install", "--global", "cf"],
        "yarn": ["yarn", "global", "add", "cf"],
        "pnpm": ["pnpm", "add", "--global", "cf"],
        "bun": ["bun", "add", "--global", "cf"],
    }
    return _plan("Install Cloudflare CLI (cf) globally", [commands[manager]], True,
                 f"Use the detected {manager} package manager; Node.js 22.18+ is required.",
                 warnings=["Bun is supported here as a package manager, but Cloudflare does not support Bun as the CLI runtime."])


def _cloudflared_install() -> dict[str, Any]:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Android" or os.environ.get("TERMUX_VERSION") or os.environ.get("ANDROID_ROOT"):
        return _plan("Install cloudflared", [], False, f"No supported automatic installation method for Termux/Android. See {CLOUDFLARE_DOWNLOADS_URL}")
    supported_architectures = {"x86_64", "amd64", "aarch64", "arm64", "armv7l", "armv7", "armhf"}
    if machine and machine not in supported_architectures:
        return _plan("Install cloudflared", [], False, f"Architecture {machine} is not supported by the safe package plans. See {CLOUDFLARE_DOWNLOADS_URL}")

    if _available("brew"):
        return _plan("Install cloudflared with Homebrew", [["brew", "install", "cloudflared"]], True, "Homebrew is available and provides the supported cloudflared package.")

    if system == "Linux":
        distro = ""
        try:
            distro = str(platform.freedesktop_os_release().get("ID", "")).lower()
        except (AttributeError, OSError, ValueError):
            pass
        rpm_family = {"fedora", "rhel", "centos", "rocky", "almalinux", "ol", "opencloudos"}
        if distro in rpm_family or (_available("dnf") and not _available("apt-get")) or (_available("yum") and not _available("apt-get")):
            repo_file = Path("/etc/yum.repos.d/cloudflared.repo")
            repo_exists = repo_file.exists()
            repo_text = ""
            if repo_exists:
                try:
                    repo_text = repo_file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass
                if "pkg.cloudflare.com/cloudflared" not in repo_text:
                    return _plan("Install cloudflared", [], False, f"{repo_file} exists but is not verified as the official Cloudflare repository. It will not be overwritten. See {CLOUDFLARE_PACKAGE_URL}")
            if not _available("sudo") and not (hasattr(os, "geteuid") and os.geteuid() == 0):
                return _plan("Install cloudflared", [], False, f"Administrative access (sudo or root) is required to configure the RPM repository. See {CLOUDFLARE_PACKAGE_URL}")
            prefix = [] if hasattr(os, "geteuid") and os.geteuid() == 0 else ["sudo"]
            if _available("dnf"):
                commands = []
                if not repo_exists:
                    check = _command(("dnf", "config-manager", "--help"))
                    if check.returncode != 0:
                        return _plan("Install cloudflared", [], False, f"dnf config-manager is required to add Cloudflare's official RPM repository. See {CLOUDFLARE_PACKAGE_URL}")
                    commands.append([*prefix, "dnf", "config-manager", "--add-repo", CLOUDFLARE_RPM_REPO])
                commands.append([*prefix, "dnf", "install", "-y", "cloudflared"])
                return _plan("Install cloudflared from the official Cloudflare RPM repository", commands, True, f"Fedora/RHEL uses the official Cloudflare RPM repository. Repository documentation: {CLOUDFLARE_PACKAGE_URL}")
            if _available("yum-config-manager") and _available("yum"):
                commands = []
                if not repo_exists:
                    commands.append([*prefix, "yum-config-manager", "--add-repo", CLOUDFLARE_RPM_REPO])
                commands.append([*prefix, "yum", "install", "-y", "cloudflared"])
                return _plan("Install cloudflared from the official Cloudflare RPM repository", commands, True, f"RHEL-compatible systems use the official Cloudflare RPM repository. Repository documentation: {CLOUDFLARE_PACKAGE_URL}")
            return _plan("Install cloudflared", [], False, f"An RPM system was detected, but no safe official repository configurator is available. See {CLOUDFLARE_PACKAGE_URL}")
        if _available("pacman") and distro in {"arch", "manjaro", "endeavouros"}:
            if not _available("sudo") and not (hasattr(os, "geteuid") and os.geteuid() == 0):
                return _plan("Install cloudflared", [], False, "Administrative access (sudo or root) is required for pacman installation.")
            prefix = [] if hasattr(os, "geteuid") and os.geteuid() == 0 else ["sudo"]
            return _plan("Install cloudflared with pacman", [[*prefix, "pacman", "-Syu", "cloudflared"]], True, "Cloudflare documents cloudflared in Arch Linux's community repository.")
        if _available("apt-get") and _available("dpkg"):
            source_file = "/etc/apt/sources.list.d/cloudflared.list"
            key_file = "/usr/share/keyrings/cloudflare-main.gpg"
            if not _available("sudo") and not (hasattr(os, "geteuid") and os.geteuid() == 0):
                return _plan("Install cloudflared", [], False, f"Administrative access (sudo or root) is required to configure the official repository. See {CLOUDFLARE_PACKAGE_URL}")
            prefix = [] if hasattr(os, "geteuid") and os.geteuid() == 0 else ["sudo"]
            if os.path.exists(source_file):
                try:
                    source_text = Path(source_file).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    source_text = ""
                if "pkg.cloudflare.com/cloudflared" in source_text:
                    return _plan("Install cloudflared from the existing Cloudflare APT repository", [[*prefix, "apt-get", "update"], [*prefix, "apt-get", "install", "-y", "cloudflared"]], True, "An existing Cloudflare repository configuration was found; it will be reused.")
                return _plan("Install cloudflared", [], False, f"{source_file} already exists but is not verified as Cloudflare's repository. Inspect it manually; no files were changed. Official instructions: {CLOUDFLARE_PACKAGE_URL}")
            if os.path.exists(key_file):
                return _plan("Install cloudflared", [], False, f"{key_file} already exists and will not be overwritten automatically. Review Cloudflare's repository instructions manually: {CLOUDFLARE_PACKAGE_URL}")
            if not _available("curl"):
                return _plan("Install cloudflared", [], False, f"curl is required to retrieve Cloudflare's official package signing key. Install curl first or follow {CLOUDFLARE_PACKAGE_URL}")
            commands = [
                [*prefix, "mkdir", "-p", "/usr/share/keyrings"],
                [*prefix, "curl", "-fsSL", CLOUDFLARE_KEY_URL, "-o", key_file],
                [*prefix, "tee", source_file],
                [*prefix, "apt-get", "update"],
                [*prefix, "apt-get", "install", "-y", "cloudflared"],
            ]
            plan = _plan("Install cloudflared from the official Cloudflare APT repository", commands, True, "Debian/Ubuntu uses the official Cloudflare APT repository and signing key.")
            plan["command_input"] = [None, None, CLOUDFLARE_APT_SOURCE + chr(10), None, None]
            return plan
    return _plan("Install cloudflared", [], False, f"No supported automatic installation method was detected for {system or 'this platform'}. Do not use arbitrary downloads; see {CLOUDFLARE_DOWNLOADS_URL}")


def plan_install(tool: str, cwd: Path | str) -> dict[str, Any]:
    """Return a confirmation-ready install plan; this function has no side effects."""
    name = tool.lower().replace("_", "-")
    directory = _path(cwd)
    detected = detect_cloudflare_tools(directory)
    if name in {"cf", "cloudflare", "cloudflare-cli"}:
        if detected["cf"]["installed"]:
            return _plan("Install Cloudflare CLI (cf)", [], False, "Cloudflare cf is already installed; use the update plan instead.")
        return _cf_install(directory)
    if name in {"wrangler", "cloudflare-wrangler"}:
        if detected["wrangler"]["installed"]:
            return _plan("Install Wrangler", [], False, "Wrangler is already installed; use the update plan instead.")
        return _wrangler_install(directory)
    if name == "cloudflared":
        if detected["cloudflared"]["installed"]:
            return _plan("Install cloudflared", [], False, "cloudflared is already installed; use the update plan instead.")
        return _cloudflared_install()
    return _plan(f"Install {tool}", [], False, f"Unsupported Cloudflare tool: {tool}")


def _wrangler_action(cwd: Path, action: str) -> dict[str, Any]:
    record = _wrangler_record(cwd)
    if not record["installed"]:
        return _plan(f"{action.title()} Wrangler", [], False, "Wrangler is not installed.")
    manager = record.get("package_manager")
    method = record.get("install_method")
    if not manager or method not in {"project", "global"}:
        return _plan(f"{action.title()} Wrangler", [], False, "Wrangler's installation method or package manager is unknown; refusing to guess.")
    if method == "project":
        package = _package_json(cwd) or {}
        is_dev = isinstance(package.get("devDependencies"), dict) and "wrangler" in package["devDependencies"]
        if action == "update":
            if manager == "npm":
                commands = ["npm", "install", *( ["--save-dev"] if is_dev else []), "wrangler@latest"]
            elif manager == "pnpm":
                commands = ["pnpm", "add", *( ["--save-dev"] if is_dev else []), "wrangler@latest"]
            elif manager == "yarn":
                commands = ["yarn", "add", *( ["--dev"] if is_dev else []), "wrangler@latest"]
            else:
                commands = ["bun", "add", *( ["--dev"] if is_dev else []), "wrangler@latest"]
        else:
            if manager == "npm":
                commands = ["npm", "uninstall", "wrangler"]
            elif manager == "pnpm":
                commands = ["pnpm", "remove", "wrangler"]
            elif manager == "yarn":
                commands = ["yarn", "remove", "wrangler"]
            else:
                commands = ["bun", "remove", "wrangler"]
    else:
        commands = (["npm", "install", "--global", "wrangler@latest"] if action == "update"
                    else ["npm", "uninstall", "--global", "wrangler"])
    return _plan(f"{action.title()} Wrangler", [commands], True, f"Use the detected {manager} {method} installation.")


def _cloudflared_action(cwd: Path, action: str) -> dict[str, Any]:
    record = _cloudflared_record(cwd)
    if not record["installed"]:
        return _plan(f"{action.title()} cloudflared", [], False, "cloudflared is not installed.")
    method = record["install_method"]
    needs_admin = method in {"apt", "dnf", "yum", "pacman"}
    if needs_admin and not _available("sudo") and not (hasattr(os, "geteuid") and os.geteuid() == 0):
        return _plan(f"{action.title()} cloudflared", [], False, "Administrative access (sudo or root) is required for this package-manager operation.")
    prefix = ["sudo"] if needs_admin and not (hasattr(os, "geteuid") and os.geteuid() == 0) else []
    commands_by_method = {
        "homebrew": {"update": ["brew", "upgrade", "cloudflared"], "uninstall": ["brew", "uninstall", "cloudflared"]},
        "apt": {"update": [*prefix, "apt-get", "install", "--only-upgrade", "-y", "cloudflared"], "uninstall": [*prefix, "apt-get", "remove", "-y", "cloudflared"]},
        "dnf": {"update": [*prefix, "dnf", "upgrade", "-y", "cloudflared"], "uninstall": [*prefix, "dnf", "remove", "-y", "cloudflared"]},
        "yum": {"update": [*prefix, "yum", "update", "-y", "cloudflared"], "uninstall": [*prefix, "yum", "remove", "-y", "cloudflared"]},
        "pacman": {"update": [*prefix, "pacman", "-Syu", "cloudflared"], "uninstall": [*prefix, "pacman", "-R", "cloudflared"]},
    }
    if method not in commands_by_method:
        return _plan(f"{action.title()} cloudflared", [], False, "cloudflared's installation method is unknown; refusing to guess an update/removal command.")
    commands = [commands_by_method[method][action]]
    if method == "apt" and action == "update":
        commands.insert(0, [*prefix, "apt-get", "update"])
    return _plan(f"{action.title()} cloudflared", commands, True, f"Use the detected {method} installation method.")


def _cf_action(cwd: Path, action: str) -> dict[str, Any]:
    record = _cf_record(cwd)
    if not record["installed"]:
        return _plan(f"{action.title()} Cloudflare CLI (cf)", [], False, "Cloudflare cf is not installed.")
    if not record.get("runtime_compatible"):
        return _plan(f"{action.title()} Cloudflare CLI (cf)", [], False,
                     f"Cloudflare cf requires Node.js 22.18 or later; detected {record.get('node_version', 'unknown')}.")
    method, manager = record["install_method"], record["package_manager"]
    if method not in {"global", "project"} or manager not in {"npm", "yarn", "pnpm", "bun"}:
        return _plan(f"{action.title()} Cloudflare CLI (cf)", [], False,
                     "The cf installation method/package manager is unknown; refusing to guess an update or removal command.")
    if method == "global":
        commands = {
            "npm": {"update": ["npm", "install", "--global", "cf@latest"], "uninstall": ["npm", "uninstall", "--global", "cf"]},
            "yarn": {"update": ["yarn", "global", "add", "cf@latest"], "uninstall": ["yarn", "global", "remove", "cf"]},
            "pnpm": {"update": ["pnpm", "add", "--global", "cf@latest"], "uninstall": ["pnpm", "remove", "--global", "cf"]},
            "bun": {"update": ["bun", "add", "--global", "cf@latest"], "uninstall": ["bun", "remove", "--global", "cf"]},
        }[manager][action]
    else:
        dev_deps = (_package_json(cwd) or {}).get("devDependencies", {})
        is_dev = isinstance(dev_deps, dict) and "cf" in dev_deps
        if action == "update":
            commands = {
                "npm": ["npm", "install", *( ["--save-dev"] if is_dev else []), "cf@latest"],
                "yarn": ["yarn", "add", *( ["--dev"] if is_dev else []), "cf@latest"],
                "pnpm": ["pnpm", "add", *( ["--save-dev"] if is_dev else []), "cf@latest"],
                "bun": ["bun", "add", *( ["--dev"] if is_dev else []), "cf@latest"],
            }[manager]
        else:
            commands = {"npm": ["npm", "uninstall", "cf"], "yarn": ["yarn", "remove", "cf"],
                        "pnpm": ["pnpm", "remove", "cf"], "bun": ["bun", "remove", "cf"]}[manager]
    return _plan(f"{action.title()} Cloudflare CLI (cf)", [commands], True,
                 f"Use the detected {manager} {method} installation.",
                 warnings=["Cloudflare's `cf` CLI requires Node.js 22.18 or later; Bun is not supported as its runtime."])


def plan_update(tool: str, cwd: Path | str) -> dict[str, Any]:
    """Return a confirmation-ready update plan without changing the machine."""
    name = tool.lower().replace("_", "-")
    directory = _path(cwd)
    if name in {"cf", "cloudflare", "cloudflare-cli"}:
        return _cf_action(directory, "update")
    if name in {"wrangler", "cloudflare-wrangler"}:
        return _wrangler_action(directory, "update")
    if name == "cloudflared":
        return _cloudflared_action(directory, "update")
    return _plan(f"Update {tool}", [], False, f"Unsupported Cloudflare tool: {tool}")


def plan_uninstall(tool: str, cwd: Path | str) -> dict[str, Any]:
    """Return a confirmation-ready uninstall plan without changing the machine."""
    name = tool.lower().replace("_", "-")
    directory = _path(cwd)
    if name in {"cf", "cloudflare", "cloudflare-cli"}:
        return _cf_action(directory, "uninstall")
    if name in {"wrangler", "cloudflare-wrangler"}:
        return _wrangler_action(directory, "uninstall")
    if name == "cloudflared":
        return _cloudflared_action(directory, "uninstall")
    return _plan(f"Uninstall {tool}", [], False, f"Unsupported Cloudflare tool: {tool}")


def execute_plan(plan: dict[str, Any], *, confirmed: bool = False, cwd: Path | str | None = None) -> dict[str, Any]:
    """Execute a plan only after explicit caller confirmation.

    This helper intentionally uses ``run`` with argv lists.  Planning and
    detection never call this function.
    """
    if not confirmed:
        return {"executed": False, "reason": "Explicit confirmation is required before executing a plan.", "results": []}
    if not plan.get("supported"):
        return {"executed": False, "reason": plan.get("reason", "Unsupported plan"), "results": []}
    results: list[dict[str, Any]] = []
    commands = plan.get("commands", [])
    command_input = plan.get("command_input", [None] * len(commands))
    for index, argv in enumerate(commands):
        stdin_text = command_input[index] if index < len(command_input) else None
        if stdin_text is None:
            result = run(argv, timeout=300, cwd=str(_path(cwd)) if cwd is not None else None)
            success = result.available and result.returncode == 0 and result.error is None
            error = result.error
            returncode = result.returncode
        else:
            try:
                completed = subprocess.run(list(argv), cwd=str(_path(cwd)) if cwd is not None else None,
                                           input=stdin_text, capture_output=True, text=True, timeout=300, check=False)
                success = completed.returncode == 0
                error = None if success else (completed.stderr.strip()[:500] or "Command failed")
                returncode = completed.returncode
            except (OSError, subprocess.TimeoutExpired) as exc:
                success, error, returncode = False, str(exc)[:500], None
        results.append({"command": list(argv), "available": returncode is not None, "returncode": returncode, "ok": success, "error": error})
        if not success:
            return {"executed": False, "reason": "A command in the plan failed.", "results": results}
    return {"executed": True, "reason": "Plan completed.", "results": results}


# Friendly alias for integrations that call this a plan runner.
run_plan = execute_plan

__all__ = [
    "detect_cloudflare_tools", "plan_install", "plan_update", "plan_uninstall",
    "execute_plan", "run_plan",
]
