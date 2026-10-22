"""Interactive, confirmation-gated Cloudflare CLI workflows."""
from __future__ import annotations

import ipaddress
import json
import os
import platform
import re
import shutil
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from .cloudflare_tools import (
    CLOUDFLARE_DOWNLOADS_URL, CLOUDFLARE_PACKAGE_URL,
    detect_cloudflare_tools, execute_plan, plan_install, plan_uninstall, plan_update,
)
from .core import run
from .inspectors import cloudflare_details
from .ui import print_result, prompt_text, render, selection_menu

TOOL_LABELS = {
    "cf": "Cloudflare CLI (cf)",
    "wrangler": "Wrangler CLI",
    "cloudflared": "Cloudflare Tunnel (cloudflared)",
}
SECRET_PATTERN = re.compile(r"(?i)(authorization\s*:\s*bearer\s+|(?:api[_ -]?token|access[_ -]?token|secret|password|credential)\s*[=:]\s*)[^\s,;]+")
QUICK_URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)


def _ask(message: str, *, warning: bool = False) -> str:
    return input(prompt_text(message, warning=warning) + " ").strip()


def _confirm(message: str) -> bool:
    return _ask(message + " [y/N]", warning=True).lower() == "y"


def _safe_text(text: str) -> str:
    safe_lines = []
    for line in text.splitlines(keepends=True):
        if re.search(r"(?i)\b(?:token|secret|password|credential|authorization|api[_ -]?key)\b", line):
            safe_lines.append("[sensitive output line suppressed]\n")
        else:
            safe_lines.append(SECRET_PATTERN.sub(r"\1[REDACTED]", line))
    return "".join(safe_lines)


def _run_quiet(argv: list[str], cwd: Path, *, timeout: int = 300) -> tuple[bool, str]:
    """Run an auth-sensitive command without displaying credentials or account output."""
    try:
        result = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, type(exc).__name__
    return result.returncode == 0, ""


def _run_filtered_until_exit(argv: list[str], cwd: Path) -> tuple[bool, str]:
    """Stream a long-running dev command while redacting credential-like output."""
    process = None
    try:
        process = subprocess.Popen(argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        if process.stdout:
            for line in process.stdout:
                print(_safe_text(line), end="", flush=True)
        return process.wait() == 0, ""
    except KeyboardInterrupt:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        print_result("Command stopped.", ok=True)
        return True, ""
    except OSError as exc:
        return False, type(exc).__name__


def _tool_command(tool: str, cwd: Path, *args: str) -> list[str] | None:
    record = detect_cloudflare_tools(cwd).get(tool, {})
    path = record.get("path")
    if not record.get("installed") or not path:
        return None
    if tool in {"wrangler", "cf"} and record.get("install_method") == "project" and os.name == "nt":
        package_name = "wrangler" if tool == "wrangler" else "cf"
        package_file = cwd / "node_modules" / package_name / "package.json"
        node = shutil.which("node")
        try:
            package = json.loads(package_file.read_text(encoding="utf-8"))
            binary = package.get("bin", {}) if isinstance(package, dict) else {}
            if isinstance(binary, dict):
                entry = binary.get("wrangler") if tool == "wrangler" else (binary.get("cf") or binary.get("cloudflare"))
            else:
                entry = binary
            entry_path = package_file.parent / entry if isinstance(entry, str) else None
            if node and entry_path and entry_path.is_file():
                return [node, str(entry_path), *args]
        except (OSError, UnicodeError, ValueError):
            pass
    return [str(path), *args]


def _show_tools(cwd: Path) -> dict[str, dict]:
    tools = detect_cloudflare_tools(cwd)
    rows = {}
    for name, record in tools.items():
        label = TOOL_LABELS.get(name, name)
        rows[label] = {
            "status": "installed" if record["installed"] else "missing",
            "version": record["version"] or ("unavailable" if record["installed"] else "not installed"),
            "path": record["path"] or "unavailable",
            "installation method": record["install_method"],
            "package manager": record["package_manager"] or "unknown",
        }
        if name == "cf":
            rows[label]["Node.js runtime"] = record.get("node_version", "unknown")
            rows[label]["runtime requirement"] = "[OK] Node.js 22.18+" if record.get("runtime_compatible") else "[WARN] Requires Node.js 22.18+"
    print(render("Detected Cloudflare Tools", rows))
    return tools


def _display_plan(plan: dict, cwd: Path) -> bool:
    print(render(plan.get("title", "Operation"), {
        "status": "supported" if plan.get("supported") else "unsupported",
        "details": plan.get("reason", ""),
        "commands": plan.get("display_commands", []),
        "warnings": plan.get("warnings", []),
    }))
    if not plan.get("supported"):
        print_result("No changes were made. Follow the official instructions shown above or choose another supported method.")
        return False
    if not _confirm("Run the exact command sequence shown above?"):
        print_result("Cancelled; no commands were run.")
        return False
    result = execute_plan(plan, confirmed=True, cwd=cwd)
    if result.get("executed"):
        print_result("Operation completed; verifying the installed tool version.", ok=True)
        _show_tools(cwd)
        return True
    print_result(result.get("reason", "Operation failed safely."), ok=False)
    for item in result.get("results", []):
        if item.get("error"):
            print(render("Command Failure", {"command": " ".join(item.get("command", [])), "error": item["error"]}))
    return False


def _install_menu(cwd: Path) -> None:
    options = {"1": "Install Cloudflare CLI (cf)", "2": "Install Wrangler CLI", "3": "Install cloudflared Tunnel client", "0": "Back to Cloudflare Toolkit"}
    choices = {"1": "cf", "2": "wrangler", "3": "cloudflared"}
    while True:
        _show_tools(cwd)
        print(selection_menu("Install Cloudflare Tools", options))
        choice = _ask("Select:")
        if choice == "0":
            return
        if choice not in choices:
            print_result("Choose a listed number.", ok=False)
            continue
        tool = choices[choice]
        managers = [name for name in ("npm", "pnpm", "yarn", "bun", "brew", "apt-get", "dnf", "yum", "pacman") if shutil.which(name)]
        runtime = {}
        for command in ("node", "npm"):
            check = run([command, "--version"], cwd=str(cwd))
            runtime[command] = (check.stdout or check.stderr or "not installed") if check.available and check.returncode == 0 else "not installed or unavailable"
        print(render("Install Preconditions", {
            "operating system": platform.system() or "unknown",
            "architecture": platform.machine() or "unknown",
            "detected package managers": managers or ["none detected"],
            "Node.js and npm versions": runtime,
            "Cloudflare cf minimum": "Node.js 22.18+" if tool == "cf" else "not applicable",
            "compatibility note": "npm reports package engine requirements; review warnings and use a supported Node.js release line.",
        }))
        _display_plan(plan_install(tool, cwd), cwd)


def _update_or_remove_menu(cwd: Path, *, uninstall: bool) -> None:
    action = "Uninstall" if uninstall else "Update"
    while True:
        tools = _show_tools(cwd)
        installed = [name for name, value in tools.items() if value["installed"]]
        options = {str(i): TOOL_LABELS.get(name, name) for i, name in enumerate(installed, 1)}
        options[str(len(installed) + 1)] = "Return"
        print(selection_menu(f"{action} Cloudflare Tools", options))
        choice = _ask("Select:")
        if choice == str(len(installed) + 1):
            return
        if not choice.isdigit() or not 1 <= int(choice) <= len(installed):
            print_result("Choose a listed number.", ok=False)
            continue
        tool = installed[int(choice) - 1]
        plan = plan_uninstall(tool, cwd) if uninstall else plan_update(tool, cwd)
        if uninstall:
            plan["warnings"] = ["Only the identified CLI package/dependency will be removed. Credentials, tunnel configuration, shared runtimes, and unrelated project files will not be deleted."]
        _display_plan(plan, cwd)


def _selected_installed_tool(cwd: Path) -> str | None:
    tools = _show_tools(cwd)
    installed = [name for name, record in tools.items() if record["installed"]]
    if not installed:
        print_result("No supported Cloudflare CLI is installed yet.")
        return None
    options = {str(i): TOOL_LABELS.get(name, name) for i, name in enumerate(installed, 1)}
    options["0"] = "Back"
    print(selection_menu("Use Installed Cloudflare Tool", options))
    choice = _ask("Select:")
    if choice == "0":
        return None
    if not choice.isdigit() or not 1 <= int(choice) <= len(installed):
        print_result("Choose a listed number.", ok=False)
        return None
    return installed[int(choice) - 1]


def _show_cli_output(tool: str, args: list[str], cwd: Path, title: str) -> None:
    argv = _tool_command(tool, cwd, *args)
    if not argv:
        print_result(f"{TOOL_LABELS.get(tool, tool)} is not installed.", ok=False)
        return
    result = run(argv, timeout=30, cwd=str(cwd))
    output = result.stdout or result.stderr or result.error or "No output."
    print(render(title, {"status": "OK" if result.returncode == 0 else "error", "output": _safe_text(output)}))


def _check_auth(cwd: Path) -> None:
    tools = detect_cloudflare_tools(cwd)
    status = {}
    if tools["cf"]["installed"] and tools["cf"].get("runtime_compatible"):
        argv = _tool_command("cf", cwd, "auth", "whoami")
        ok, _ = _run_quiet(argv or [], cwd, timeout=30) if argv else (False, "not installed")
        status["Cloudflare cf"] = "[OK] Authenticated (account details suppressed)" if ok else "[WARN] Not authenticated or status unavailable"
    elif tools["cf"]["installed"]:
        status["Cloudflare cf"] = "[WARN] Node.js 22.18+ required; not queried"
    else:
        status["Cloudflare cf"] = "[WARN] Not installed"
    if tools["wrangler"]["installed"]:
        argv = _tool_command("wrangler", cwd, "whoami")
        ok, _ = _run_quiet(argv or [], cwd, timeout=30) if argv else (False, "not installed")
        status["Wrangler"] = "[OK] Authenticated (account details suppressed)" if ok else "[WARN] Not authenticated or status unavailable"
    else:
        status["Wrangler"] = "[WARN] Not installed"
    cert = Path.home() / ".cloudflared" / "cert.pem"
    status["cloudflared"] = "[OK] Account certificate present (contents not read)" if cert.is_file() else "[WARN] No account certificate detected"
    print(render("Cloudflare Authentication Status", status))


def _auth_menu(cwd: Path) -> None:
    options = {
        "1": "Check authentication status",
        "2": "Authenticate Wrangler (OAuth browser flow)",
        "3": "Log out of Wrangler",
        "4": "Authenticate cloudflared named-tunnel management",
        "5": "Authenticate Cloudflare CLI (cf)",
        "6": "Log out of Cloudflare CLI (cf)",
        "0": "Back",
    }
    while True:
        _check_auth(cwd)
        print(selection_menu("Cloudflare Authentication", options))
        choice = _ask("Select:")
        if choice == "0":
            return
        if choice == "1":
            continue
        if choice in {"2", "3", "4", "5", "6"}:
            if choice in {"2", "3"}:
                tool, args = "wrangler", ["login" if choice == "2" else "logout"]
                operation = "start Wrangler OAuth login" if choice == "2" else "log out of Wrangler"
            elif choice == "4":
                tool, args, operation = "cloudflared", ["tunnel", "login"], "open Cloudflare tunnel authentication"
            else:
                tool, args = "cf", ["auth", "login" if choice == "5" else "logout"]
                operation = "start cf OAuth login" if choice == "5" else "log out of the separate cf credential store"
            argv = _tool_command(tool, cwd, *args)
            if not argv:
                print_result(f"{TOOL_LABELS[tool]} is not installed.", ok=False)
                continue
            if tool == "cf" and not detect_cloudflare_tools(cwd)["cf"].get("runtime_compatible"):
                print_result("Cloudflare cf requires Node.js 22.18 or later.", ok=False)
                continue
            if not _confirm(f"Confirm you want to {operation}? Account details and one-time codes will be suppressed."):
                print_result("Cancelled; authentication was not changed.")
                continue
            ok, error = _run_quiet(argv, cwd, timeout=600)
            message = "Authentication flow completed; sensitive output was suppressed." if ok else f"Authentication failed or timed out ({error or 'non-zero exit status'}); output suppressed."
            print_result(message, ok=ok)
        else:
            print_result("Choose a listed number.", ok=False)


def _loopback_url(raw: str) -> tuple[str | None, str | None]:
    value = raw.strip()
    if value.isdigit():
        value = "http://127.0.0.1:" + value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None, "Enter a port number or a complete http:// or https:// URL."
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        return None, "For safety, provide only the local service origin; paths, credentials, queries, and fragments are not accepted."
    host = parsed.hostname.lower()
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        return None, "For safety, Quick Tunnels are limited to localhost or a loopback IP address."
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None, "The URL contains an invalid port."
    if not 1 <= port <= 65535:
        return None, "The port must be between 1 and 65535."
    netloc = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    return f"{parsed.scheme}://{netloc}", None


def _server_reachable(url: str) -> bool:
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or (443 if parsed.scheme == "https" else 80)), timeout=1.0):
            return True
    except OSError:
        return False


def _run_quick_tunnel(argv: list[str], cwd: Path) -> None:
    process = None
    public_url = None
    try:
        process = subprocess.Popen(argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        if process.stdout:
            for line in process.stdout:
                match = QUICK_URL_PATTERN.search(line)
                if match:
                    public_url = match.group(0)
                    print_result(f"Temporary public tunnel URL: {public_url}", ok=True)
                    print_result("Anyone with the URL can access this local service. Press Ctrl+C to stop the tunnel.")
        code = process.wait()
        if code != 0:
            print_result(f"Tunnel exited with status {code}; logs were suppressed.", ok=False)
        elif not public_url:
            print_result("Tunnel ended without a public URL; logs were suppressed.", ok=False)
    except KeyboardInterrupt:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        print_result("Temporary tunnel stopped.", ok=True)
    except OSError as exc:
        print_result(f"Could not start cloudflared: {type(exc).__name__}", ok=False)


def _named_tunnels(cwd: Path, *, deleting: bool = False) -> None:
    argv = _tool_command("cloudflared", cwd, "tunnel", "list")
    if not argv:
        print_result("cloudflared is not installed.", ok=False)
        return
    try:
        result = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        print_result("Could not query named tunnels. Check installation and authentication.", ok=False)
        return
    if result.returncode != 0:
        print_result("Could not list tunnels; authenticate with cloudflared tunnel login if intended.", ok=False)
        return
    if not deleting:
        print(render("Named Cloudflare Tunnels", {"status": "OK", "tunnel list": _safe_text(result.stdout or "No tunnels returned.")}))
        return
    name = _ask("Name or UUID of tunnel to delete:")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", name):
        print_result("Tunnel name/UUID must contain only letters, numbers, and hyphens.", ok=False)
        return
    info = _tool_command("cloudflared", cwd, "tunnel", "info", name)
    check = run(info or [], timeout=30, cwd=str(cwd)) if info else None
    if not check or check.returncode != 0:
        print_result("Tunnel was not verified; nothing was deleted.", ok=False)
        return
    if not _confirm(f"Permanently delete Cloudflare tunnel {name!r}? This removes the remote tunnel resource, not local configuration."):
        print_result("Cancelled; tunnel was not deleted.")
        return
    delete = _tool_command("cloudflared", cwd, "tunnel", "delete", name)
    ok, _ = _run_quiet(delete or [], cwd, timeout=120) if delete else (False, "unavailable")
    print_result(f"Tunnel {name!r} deleted." if ok else "Tunnel deletion failed; output was suppressed.", ok=ok)


def _tunnel_menu(cwd: Path) -> None:
    options = {
        "1": "Show version and help",
        "2": "Inspect local configuration filenames and authentication",
        "3": "List named tunnels",
        "4": "Create a named tunnel",
        "5": "Delete a named tunnel",
        "6": "Run temporary Quick Tunnel to a local server",
        "0": "Back",
    }
    while True:
        _show_tools(cwd)
        print(selection_menu("Cloudflare Tunnel Management", options))
        choice = _ask("Select:")
        if choice == "0":
            return
        if choice == "1":
            _show_cli_output("cloudflared", ["--help"], cwd, "cloudflared Help")
        elif choice == "2":
            config_dir = Path.home() / ".cloudflared"
            files = [p.name for p in config_dir.iterdir() if p.is_file()] if config_dir.is_dir() else []
            configs = [name for name in files if name in {"config.yml", "config.yaml"}]
            cred_count = sum(name.endswith(".json") for name in files)
            print(render("Local Tunnel Configuration", {
                "configuration filenames": configs,
                "tunnel credential files": f"{cred_count} present (names and contents hidden)",
                "account certificate": "present (contents not read)" if "cert.pem" in files else "not found",
            }))
        elif choice == "3":
            _named_tunnels(cwd)
        elif choice == "4":
            name = _ask("New tunnel name:")
            if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", name):
                print_result("Use 1-128 letters, numbers, or hyphens.", ok=False)
                continue
            argv = _tool_command("cloudflared", cwd, "tunnel", "create", name)
            if not argv:
                print_result("cloudflared is not installed.", ok=False)
            elif _confirm(f"Create named tunnel {name!r} in the authenticated Cloudflare account?"):
                ok, _ = _run_quiet(argv, cwd, timeout=120)
                print_result(f"Tunnel {name!r} created; credentials were not displayed." if ok else "Tunnel creation failed; output was suppressed.", ok=ok)
            else:
                print_result("Cancelled; no named tunnel was created.")
        elif choice == "5":
            _named_tunnels(cwd, deleting=True)
        elif choice == "6":
            url, error = _loopback_url(_ask("Local port or loopback URL (example: 8080 or http://127.0.0.1:8080):"))
            if error:
                print_result(error, ok=False)
                continue
            if not _server_reachable(url):
                print_result(f"No local server responded at {url}; no tunnel was started.", ok=False)
                continue
            print_result(f"Temporary Quick Tunnel will publicly expose {url}. Anyone with its URL may access the local service.")
            if not _confirm("Create this temporary public tunnel?"):
                print_result("Cancelled; no tunnel was started.")
                continue
            argv = _tool_command("cloudflared", cwd, "tunnel", "--url", url)
            if argv:
                _run_quick_tunnel(argv, cwd)
            else:
                print_result("cloudflared is not installed.", ok=False)
        else:
            print_result("Choose a listed number.", ok=False)


def _project_menu(cwd: Path) -> None:
    options = {"1": "Show local Wrangler config", "2": "Show Wrangler help", "3": "Start wrangler dev", "4": "Deploy with Wrangler", "0": "Back"}
    while True:
        print(render("Workers & Pages Project", cloudflare_details(cwd)))
        print(selection_menu("Wrangler Project Actions", options))
        choice = _ask("Select:")
        if choice == "0":
            return
        if choice == "1":
            continue
        if choice == "2":
            _show_cli_output("wrangler", ["--help"], cwd, "Wrangler Help")
            continue
        if choice not in {"3", "4"}:
            print_result("Choose a listed number.", ok=False)
            continue
        args = ["dev"] if choice == "3" else ["deploy"]
        if choice == "4":
            print_result("Deployment changes a live Cloudflare account. Review the current project and account first.")
        if not _confirm(f"Run `wrangler {' '.join(args)}` in {cwd}?"):
            print_result("Cancelled; no Wrangler command was run.")
            continue
        argv = _tool_command("wrangler", cwd, *args)
        if not argv:
            print_result("Wrangler is not installed.", ok=False)
            continue
        ok, error = _run_filtered_until_exit(argv, cwd)
        print_result("Wrangler command completed; output was filtered/suppressed." if ok else f"Wrangler command failed ({error or 'non-zero exit status'}); sensitive output suppressed.", ok=ok)


def _cf_project_menu(cwd: Path) -> None:
    wrangler_files = [name for name in ("wrangler.toml", "wrangler.json", "wrangler.jsonc") if (cwd / name).is_file()]
    cf_files = [name for name in ("cloudflare.config.ts", "cloudflare.config.js") if (cwd / name).is_file()]
    print(render("Cloudflare CLI Project", {"directory": str(cwd), "Wrangler configuration": wrangler_files, "cf configuration": cf_files}))
    options = {"1": "Show project files", "2": "Start cf dev", "3": "Deploy with cf deploy", "4": "Show migration guidance (no changes)", "0": "Back"}
    while True:
        print(selection_menu("Cloudflare `cf` Project Actions", options))
        choice = _ask("Select:")
        if choice == "0":
            return
        if choice == "1":
            print(render("Project Files", {"Wrangler configuration": wrangler_files, "cf configuration": cf_files, "package.json": (cwd / "package.json").is_file()}))
        elif choice == "4":
            print(render("Migration Guidance", {"official guide": "https://developers.cloudflare.com/cf/wrangler/migrate/", "safety": "Commit or stash all changes first. This toolkit never runs cf migrate or rewrites Wrangler project files automatically."}))
        elif choice in {"2", "3"}:
            if wrangler_files:
                print_result("This project has Wrangler configuration. Cloudflare documents `cf migrate` before cf dev/deploy in Wrangler projects; this toolkit will not migrate or alter your files. Review the official migration guide first.", ok=False)
                continue
            if not detect_cloudflare_tools(cwd)["cf"].get("runtime_compatible"):
                print_result("Cloudflare cf requires Node.js 22.18 or later.", ok=False)
                continue
            args = ["dev"] if choice == "2" else ["deploy"]
            if choice == "3":
                print_result("This will deploy project resources to a live Cloudflare account.")
            if not _confirm(f"Run `cf {' '.join(args)}` in {cwd}?"):
                print_result("Cancelled; no cf command was run.")
                continue
            argv = _tool_command("cf", cwd, *args)
            if not argv:
                print_result("Cloudflare cf is not installed.", ok=False)
                continue
            ok, error = _run_filtered_until_exit(argv, cwd)
            print_result("cf command completed; sensitive output was suppressed." if ok else f"cf command failed ({error or 'non-zero exit status'}); sensitive output suppressed.", ok=ok)
        else:
            print_result("Choose a listed number.", ok=False)


def _cf_menu(cwd: Path) -> None:
    options = {"1": "Show version", "2": "Show help", "3": "Check cf login status", "4": "Authenticate with cf", "5": "Search for a CLI command", "6": "Open cf Workers project actions", "0": "Back"}
    while True:
        if not detect_cloudflare_tools(cwd)["cf"].get("runtime_compatible"):
            print_result("Cloudflare cf requires Node.js 22.18 or later; command actions may be unavailable.", ok=False)
        print(selection_menu("Cloudflare CLI (cf)", options))
        choice = _ask("Select:")
        if choice == "0":
            return
        if choice == "1":
            _show_cli_output("cf", ["--version"], cwd, "Cloudflare cf Version")
        elif choice == "2":
            _show_cli_output("cf", ["--help"], cwd, "Cloudflare cf Help")
        elif choice == "3":
            _check_auth(cwd)
        elif choice == "4":
            _auth_menu(cwd)
        elif choice == "5":
            task = _ask("Describe the Cloudflare command you need:")
            if task:
                _show_cli_output("cf", ["cli", "search", task], cwd, "Suggested Cloudflare Commands")
        elif choice == "6":
            _cf_project_menu(cwd)
        else:
            print_result("Choose a listed number.", ok=False)


def _use_menu(cwd: Path) -> None:
    while True:
        tool = _selected_installed_tool(cwd)
        if not tool:
            return
        if tool == "cf":
            _cf_menu(cwd)
            return
        if tool == "cloudflared":
            _tunnel_menu(cwd)
            return
        options = {"1": "Show version", "2": "Show supported commands/help", "3": "Check login status", "4": "Authentication options", "5": "Inspect Workers/Pages project", "6": "Open Workers & Pages actions", "0": "Back"}
        while True:
            print(selection_menu("Wrangler CLI", options))
            choice = _ask("Select:")
            if choice == "0":
                return
            if choice == "1":
                _show_cli_output("wrangler", ["--version"], cwd, "Wrangler Version")
            elif choice == "2":
                _show_cli_output("wrangler", ["--help"], cwd, "Wrangler Commands")
            elif choice == "3":
                _check_auth(cwd)
            elif choice == "4":
                _auth_menu(cwd)
            elif choice == "5":
                print(render("Workers & Pages Project", cloudflare_details(cwd)))
            elif choice == "6":
                _project_menu(cwd)
            else:
                print_result("Choose a listed number.", ok=False)


def _discover() -> None:
    print(render("Official Cloudflare CLI Sources", {
        "Cloudflare cf CLI install/sign-in": "https://developers.cloudflare.com/cf/get-started/",
        "Cloudflare cf CLI": "https://developers.cloudflare.com/cf/",
        "Wrangler install and update": "https://developers.cloudflare.com/workers/wrangler/install-and-update/",
        "Wrangler commands and authentication": "https://developers.cloudflare.com/workers/wrangler/commands/",
        "cloudflared downloads": CLOUDFLARE_DOWNLOADS_URL,
        "Cloudflare package repository": CLOUDFLARE_PACKAGE_URL,
        "Quick Tunnels": "https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/",
        "Named tunnels": "https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/create-local-tunnel/",
        "Termux/Android": "No official Termux-specific cloudflared package was found in Cloudflare's documented methods; arbitrary binaries are not installed.",
    }))


def cloudflare_menu(cwd: Path | None = None) -> None:
    cwd = cwd or Path.cwd()
    options = {"1": "Install Cloudflare Tools", "2": "Use Cloudflare Tools", "3": "Update Cloudflare Tools", "4": "Uninstall Cloudflare Tools", "5": "Check Installation & Versions", "6": "Cloudflare Authentication", "7": "Workers & Pages Project Tools", "8": "Cloudflare Tunnel Management", "9": "Discover More Cloudflare Tools", "0": "Back to Main Menu"}
    while True:
        _show_tools(cwd)
        print(selection_menu("Cloudflare Toolkit", options))
        choice = _ask("Select:")
        if choice == "0":
            return
        if choice == "1":
            _install_menu(cwd)
        elif choice == "2":
            _use_menu(cwd)
        elif choice == "3":
            _update_or_remove_menu(cwd, uninstall=False)
        elif choice == "4":
            _update_or_remove_menu(cwd, uninstall=True)
        elif choice == "5":
            _show_tools(cwd)
        elif choice == "6":
            _auth_menu(cwd)
        elif choice == "7":
            _project_menu(cwd)
        elif choice == "8":
            _tunnel_menu(cwd)
        elif choice == "9":
            _discover()
        else:
            print_result("Choose a listed number.", ok=False)
