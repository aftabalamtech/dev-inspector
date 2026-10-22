"""Terminal UI for safe self-updates."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import updater
from .ui import print_result, prompt_text, render, selection_menu


def _ask(message: str, *, warning: bool = False) -> str:
    return input(prompt_text(message, warning=warning) + " ").strip()


def _confirm(message: str) -> bool:
    return _ask(message + " [y/N]", warning=True).lower() == "y"


def _short(value: Any) -> str:
    text = str(value or "unavailable")
    return text if len(text) <= 12 else text[:12]


def _summary(state: dict[str, Any]) -> dict[str, Any]:
    behind = state.get("commits_behind", "unavailable")
    ahead = state.get("commits_ahead", "unavailable")
    status = state.get("update_status", state.get("status", "unavailable")).replace("_", " ").title()
    return {
        "current version": state.get("current_version", "unavailable"),
        "current commit": _short(state.get("current_commit")),
        "latest available version": state.get("latest_version", "not checked"),
        "latest available commit": _short(state.get("latest_commit")) if state.get("latest_commit") else "not checked",
        "commits behind upstream": behind,
        "commits ahead of upstream": ahead,
        "current branch": state.get("branch", "unavailable"),
        "upstream branch": state.get("upstream", "unavailable"),
        "verified repository": state.get("remote_repository", "unavailable"),
        "update status": status,
    }


def _show_state(state: dict[str, Any], title: str = "Dev Inspector Version & Update Status") -> None:
    print(render(title, _summary(state)))
    if state.get("dirty_files"):
        print(render("Local Changes (not modified by updater)", state["dirty_files"]))
    if state.get("message"):
        succeeded = state.get("status") == "up_to_date"
        print_result(state["message"], ok=True if succeeded else (False if not state.get("ok") else None))


def _show_commit_changes(state: dict[str, Any]) -> None:
    commits = state.get("new_commits", [])
    if commits:
        print(render("Incoming Commits", commits))
    else:
        print_result("No incoming commits were found.", ok=True)
    if state.get("diff_stat"):
        print(render("Incoming Change Summary", {"files and lines": state["diff_stat"]}))


def _update_to_latest() -> None:
    state = updater.check_for_updates()
    _show_state(state, "Update Preview")
    if not state.get("ok"):
        if state.get("status") == "remote_mismatch":
            print_result("Change the configured upstream only if you own/trust it, then verify its URL. No application files were changed.", ok=False)
        return
    status = state.get("update_status")
    if status == "up_to_date":
        print_result("Dev Inspector is already up to date.", ok=True)
        return
    if status == "local_ahead":
        print_result("Your local branch is ahead of the upstream. The updater will not replace local commits.")
        return
    if status == "diverged":
        print_result("The local branch and upstream have diverged. No update was applied. Back up your work, inspect `git log --graph --oneline --decorate --all`, then reconcile branches manually; the updater will not reset or rebase.", ok=False)
        return
    if state.get("dirty_files"):
        print_result("Commit, move, or otherwise safely preserve all listed changes, then check again. The updater never stashes or discards work.", ok=False)
        return
    if status != "updates_available":
        print_result("No safe fast-forward update is available.", ok=False)
        return
    _show_commit_changes(state)
    if not _confirm(f"Fast-forward branch {state['branch']!r} from {_short(state['current_commit'])} to verified upstream commit {_short(state['latest_commit'])}?"):
        print_result("Update cancelled; the working tree was not changed.")
        return
    result = updater.apply_update(state)
    if result.get("ok"):
        print(render("Update Complete", {
            "branch": result["branch"],
            "previous commit": _short(result["previous_commit"]),
            "current commit": _short(result["current_commit"]),
            "verification": "[OK] Final commit matches verified upstream",
        }))
        print_result(result["message"], ok=True)
        print_result("Restart Dev Inspector to run the updated code.")
    else:
        print_result(result.get("message", "Update failed safely; inspect Git status before retrying."), ok=False)


def _check_for_updates() -> None:
    state = updater.check_for_updates()
    _show_state(state, "Update Check")
    if not state.get("ok"):
        return
    if state.get("update_status") == "up_to_date":
        print_result("No update is available.", ok=True)
        if state.get("dirty_files"):
            print_result("Your local changes are preserved; they would only block an update when one is available.")
    elif state.get("status") == "local_changes":
        print_result("The remote check succeeded, but the working tree has changes. Updating is blocked until you resolve them.")
    elif state.get("update_status") == "updates_available":
        print_result(f"{state['commits_behind']} upstream commit(s) are available. Choose Update to Latest Version to review them.")
        _show_commit_changes(state)
    elif state.get("update_status") == "local_ahead":
        print_result("The local branch is ahead of upstream; no remote update is available.")
    elif state.get("update_status") == "diverged":
        print_result("Local and upstream branches have diverged. Resolve the branch history manually; no update was applied.", ok=False)


def _view_current_version() -> None:
    state = updater.current_version()
    _show_state(state, "Current Dev Inspector Version")
    if state.get("ok") and state.get("dirty_files"):
        print_result("The checkout has local changes; self-update will refuse to overwrite them.")


def _view_recent_changes() -> None:
    state = updater.recent_changes()
    if not state.get("change_scope"):
        _show_state(state, "Recent Changes")
        return
    scope = "Available Upstream Changes" if state.get("change_scope") == "upstream" else "Recent Local Commits"
    _show_state(state, scope)
    commits = state.get("recent_changes", [])
    if commits:
        print(render(scope, commits))
    else:
        print_result("No commit messages are available.")
    if state.get("change_scope") == "local" and state.get("status") in {"network_error", "fetch_error", "fetch_verification_failed", "compare_error"}:
        print_result("Showing local history because the upstream could not be reached.")


def update_manager_menu() -> None:
    options = {
        "1": "Update to Latest Version",
        "2": "Check for Updates",
        "3": "View Current Version",
        "4": "View Recent Changes",
        "0": "Back to Main Menu",
    }
    while True:
        print(selection_menu("Dev Inspector Update Manager", options))
        choice = _ask("Select:")
        if choice == "0":
            return
        try:
            if choice == "1":
                _update_to_latest()
            elif choice == "2":
                _check_for_updates()
            elif choice == "3":
                _view_current_version()
            elif choice == "4":
                _view_recent_changes()
            else:
                print_result("Choose a listed number.", ok=False)
        except EOFError:
            print_result("Update manager closed safely.")
            return
        except KeyboardInterrupt:
            print_result("Update operation cancelled safely.")
        except Exception as exc:
            print_result(f"Update operation stopped safely: {type(exc).__name__}.", ok=False)
