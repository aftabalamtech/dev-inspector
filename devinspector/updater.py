"""Safe, Git-metadata-driven self-update checks for Dev Inspector."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .core import CommandResult

EXPECTED_REPOSITORY = "aftabalamtech/dev-inspector"
EXPECTED_REMOTE_URL = "https://github.com/aftabalamtech/dev-inspector.git"


def _git(args: list[str], cwd: Path, *, timeout: int = 30, disable_hooks: bool = False) -> CommandResult:
    """Run Git without a shell and without allowing credential prompts to hang."""
    if shutil.which("git") is None:
        return CommandResult(False, error="Git is not installed or not available on PATH.")
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    hook_directory = None
    try:
        if disable_hooks:
            hook_directory = tempfile.TemporaryDirectory(prefix="dev-inspector-empty-hooks-")
        command = [
            "git", "-c", "color.ui=false", "-c", "color.status=false",
            "-c", "color.diff=false", "-c", "color.log=false",
            "-c", "color.branch=false", "-c", "color.decorate=false", "-c", "core.quotePath=true",
        ]
        if hook_directory is not None:
            command.extend(["-c", f"core.hooksPath={hook_directory.name}"])
        command.extend(["--no-pager", *args])
        result = subprocess.run(command, cwd=str(cwd), env=env,
                                capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return CommandResult(True, error="Git command timed out.")
    except KeyboardInterrupt:
        return CommandResult(True, error="Git command was interrupted; inspect repository status before retrying.")
    except OSError as exc:
        return CommandResult(False, error=f"Git could not run ({type(exc).__name__}).")
    finally:
        if hook_directory is not None:
            hook_directory.cleanup()
    # Do not strip leading spaces: porcelain status uses them as XY columns.
    return CommandResult(True, result.stdout.rstrip("\r\n"), result.stderr.strip(), result.returncode)


def _ok(result: CommandResult) -> bool:
    return result.available and result.returncode == 0 and result.error is None


def _value(result: CommandResult) -> str | None:
    return result.stdout.strip() if _ok(result) and result.stdout.strip() else None


def _safe_log_lines(text: str) -> list[str]:
    """Commit subjects are repository-controlled; redact common secret forms before display."""
    safe = []
    for line in text.splitlines():
        line = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line)
        line = re.sub(r"(?i)\b(github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9_]+|xox[baprs]-[A-Za-z0-9-]+)\b", "[REDACTED]", line)
        line = re.sub(r"(?i)\b(token|secret|password|passwd|credential|authorization|api[_ -]?(?:key|token)|access[_ -]?key|private[_ -]?key)\s*[:=]\s*\S+", r"\1=[REDACTED]", line)
        line = re.sub(r"(https?://)[^/@\s]+(?::[^/@\s]*)?@", r"\1[REDACTED]@", line)
        safe.append(line)
    return safe


def normalize_github_repository(remote_url: str) -> str | None:
    """Return owner/repository for supported GitHub HTTPS, SSH, or SCP-style URLs."""
    value = remote_url.strip()
    scp = re.fullmatch(r"(?:[^@/]+@)?github\.com:([^?#]+)", value, flags=re.IGNORECASE)
    if scp:
        path = scp.group(1)
    else:
        try:
            parsed = urlsplit(value)
        except ValueError:
            return None
        if parsed.scheme.lower() not in {"https", "ssh"} or (parsed.hostname or "").lower() != "github.com":
            return None
        if parsed.query or parsed.fragment:
            return None
        path = parsed.path.lstrip("/")
    path = path.rstrip("/")
    if path.lower().endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part or "") for part in parts):
        return None
    return "/".join(parts).lower()


def application_repository_path() -> Path:
    """Locate this source checkout independent of the shell's current directory."""
    return Path(__file__).resolve().parent.parent


def _count(repo: Path, revision_range: str) -> int | None:
    result = _git(["rev-list", "--count", revision_range], repo)
    value = _value(result)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _tracked_changes(repo: Path) -> list[str] | None:
    result = _git(["status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none"], repo)
    if not _ok(result):
        return None
    changes = []
    for line in result.stdout.splitlines():
        if len(line) >= 4:
            changes.append(line[3:])
        elif line:
            changes.append(line)
    return changes


def _context(repo_path: Path | str | None = None) -> dict[str, Any]:
    candidate = Path(repo_path).expanduser().resolve() if repo_path is not None else application_repository_path()
    if shutil.which("git") is None:
        return {"ok": False, "status": "git_missing", "message": "Git is required for self-updates but was not found on PATH."}
    root_value = _value(_git(["rev-parse", "--show-toplevel"], candidate))
    if root_value is None:
        return {"ok": False, "status": "not_git_repository", "message": "This installation is not a Git checkout. Self-update is available only for a Git clone."}
    root = Path(root_value).resolve()
    if root != candidate:
        return {"ok": False, "status": "not_repository_root", "message": "The application path does not match the root of its Git repository."}
    branch = _value(_git(["branch", "--show-current"], root))
    if not branch:
        return {"ok": False, "status": "detached_head", "repo": str(root), "message": "The checkout is not on a local branch; switch to a branch with an upstream before updating."}
    current_commit = _value(_git(["rev-parse", "HEAD"], root))
    current_version = _value(_git(["describe", "--tags", "--always", "--dirty"], root))
    if not current_commit:
        return {"ok": False, "status": "invalid_head", "repo": str(root), "message": "Git could not identify the current commit."}
    remote = _value(_git(["config", "--get", f"branch.{branch}.remote"], root))
    merge_ref = _value(_git(["config", "--get", f"branch.{branch}.merge"], root))
    if not remote or remote == "." or not merge_ref or not merge_ref.startswith("refs/heads/"):
        return {"ok": False, "status": "upstream_missing", "repo": str(root), "branch": branch,
                "current_commit": current_commit, "current_version": current_version,
                "message": "This branch has no configured remote upstream. Configure an upstream branch before self-updating."}
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", remote):
        return {"ok": False, "status": "invalid_remote_name", "repo": str(root), "branch": branch,
                "message": "The configured remote name is unsupported; no update was attempted."}
    remote_url = _value(_git(["remote", "get-url", remote], root))
    repository = normalize_github_repository(remote_url or "")
    if repository != EXPECTED_REPOSITORY:
        shown = repository or "unrecognized remote"
        return {"ok": False, "status": "remote_mismatch", "repo": str(root), "branch": branch,
                "current_commit": current_commit, "current_version": current_version,
                "remote_name": remote, "remote_repository": shown,
                "message": f"Configured upstream remote is {shown}, not the expected {EXPECTED_REPOSITORY}. No network update was attempted."}
    upstream_branch = merge_ref.removeprefix("refs/heads/")
    tracking_ref = f"refs/remotes/{remote}/{upstream_branch}"
    ref_check = _git(["check-ref-format", tracking_ref], root)
    if not _ok(ref_check):
        return {"ok": False, "status": "invalid_upstream", "repo": str(root), "branch": branch,
                "message": "The configured upstream branch name is invalid; no update was attempted."}
    changes = _tracked_changes(root)
    if changes is None:
        return {"ok": False, "status": "git_error", "repo": str(root), "message": "Git could not inspect the working tree."}
    return {
        "ok": True, "status": "ready", "repo": str(root), "branch": branch,
        "current_commit": current_commit, "current_version": current_version or current_commit[:12],
        "remote_name": remote, "remote_repository": repository, "merge_ref": merge_ref,
        "upstream_branch": upstream_branch, "upstream": f"{remote}/{upstream_branch}",
        "tracking_ref": tracking_ref, "dirty_files": changes,
    }


def check_for_updates(repo_path: Path | str | None = None) -> dict[str, Any]:
    """Verify Git/repository/upstream, test network reachability, and fetch one upstream branch."""
    state = _context(repo_path)
    if not state.get("ok"):
        return state
    repo = Path(state["repo"])
    remote, merge_ref, tracking_ref = state["remote_name"], state["merge_ref"], state["tracking_ref"]
    probe = _git(["ls-remote", "--heads", remote, merge_ref], repo, timeout=45)
    if not _ok(probe):
        state.update(ok=False, status="network_error", message="Could not reach the verified GitHub upstream. Check internet access, DNS, or existing Git credentials; Git output was suppressed.")
        return state
    remote_line = next((line.split() for line in probe.stdout.splitlines() if len(line.split()) == 2 and line.split()[1] == merge_ref), None)
    if not remote_line or not re.fullmatch(r"[0-9a-fA-F]{40,64}", remote_line[0]):
        state.update(ok=False, status="upstream_branch_missing", message="The configured upstream branch was not found on the verified remote.")
        return state
    probe_commit = remote_line[0].lower()
    refspec = f"{merge_ref}:{tracking_ref}"
    fetched = _git(["fetch", "--no-tags", remote, refspec], repo, timeout=120, disable_hooks=True)
    if not _ok(fetched):
        state.update(ok=False, status="fetch_error", message="Git could not fetch the verified upstream branch. Working files were not changed; Git output was suppressed.")
        return state
    latest = _value(_git(["rev-parse", tracking_ref], repo))
    if not latest or latest.lower() != probe_commit:
        state.update(ok=False, status="fetch_verification_failed", message="The fetched branch did not match the remote commit just checked. No application files were changed.")
        return state
    behind = _count(repo, f"HEAD..{latest}")
    ahead = _count(repo, f"{latest}..HEAD")
    if behind is None or ahead is None:
        state.update(ok=False, status="compare_error", message="Git could not compare the local and remote commits.")
        return state
    if behind and ahead:
        update_status = "diverged"
    elif behind:
        update_status = "updates_available"
    elif ahead:
        update_status = "local_ahead"
    else:
        update_status = "up_to_date"
    latest_version = _value(_git(["describe", "--tags", "--always", latest], repo)) or latest[:12]
    changes = _git(["log", "--oneline", "--no-decorate", f"HEAD..{latest}"], repo)
    diffstat = _git(["diff", "--stat", "HEAD", latest], repo)
    state.update(
        ok=True,
        status="local_changes" if state["dirty_files"] else update_status,
        update_status=update_status,
        latest_commit=latest,
        latest_version=latest_version,
        commits_behind=behind,
        commits_ahead=ahead,
        new_commits=_safe_log_lines(changes.stdout)[:20] if _ok(changes) else [],
        diff_stat=diffstat.stdout if _ok(diffstat) else "",
        message=("The working tree has local changes; they will not be overwritten." if state["dirty_files"] else update_status.replace("_", " ").capitalize()),
    )
    return state


def current_version(repo_path: Path | str | None = None) -> dict[str, Any]:
    """Report the installed version from local Git metadata without network access."""
    state = _context(repo_path)
    if not state.get("ok"):
        return state
    return {
        "ok": True, "status": "local_version", "repo": state["repo"], "branch": state["branch"],
        "current_commit": state["current_commit"], "current_version": state["current_version"],
        "upstream": state["upstream"], "remote_repository": state["remote_repository"],
        "dirty_files": state["dirty_files"],
    }


def apply_update(state: dict[str, Any]) -> dict[str, Any]:
    """Fast-forward only after a caller has displayed the plan and obtained confirmation."""
    if not state.get("ok") or state.get("update_status") != "updates_available":
        return {"ok": False, "status": "not_applicable", "message": "There is no safe fast-forward update to apply."}
    root = Path(state["repo"])
    fresh = _context(root)
    if not fresh.get("ok"):
        return {"ok": False, "status": fresh.get("status"), "message": fresh.get("message", "Repository verification failed.")}
    if fresh["dirty_files"]:
        return {"ok": False, "status": "local_changes", "dirty_files": fresh["dirty_files"],
                "message": "The working tree changed after the update preview. Nothing was applied."}
    if fresh["current_commit"] != state.get("current_commit"):
        return {"ok": False, "status": "local_head_changed", "message": "The local commit changed after the preview. Check for updates again before applying."}
    if fresh["branch"] != state.get("branch"):
        return {"ok": False, "status": "local_branch_changed", "message": "The current branch changed after the preview. Check for updates again before applying."}
    if fresh["remote_name"] != state.get("remote_name") or fresh["tracking_ref"] != state.get("tracking_ref"):
        return {"ok": False, "status": "upstream_changed", "message": "The configured upstream changed after the preview. Check for updates again."}
    latest_now = _value(_git(["rev-parse", fresh["tracking_ref"]], root))
    if latest_now != state.get("latest_commit"):
        return {"ok": False, "status": "remote_advanced", "message": "The upstream commit changed after the preview. Check for updates again; nothing was applied."}
    merge = _git(["merge", "--ff-only", "--no-overwrite-ignore", state["latest_commit"]], root, timeout=120, disable_hooks=True)
    if not _ok(merge):
        return {"ok": False, "status": "fast_forward_failed", "message": "Git could not fast-forward safely. No reset or cleanup was attempted; inspect the repository and retry."}
    final_commit = _value(_git(["rev-parse", "HEAD"], root))
    if final_commit != state.get("latest_commit"):
        return {"ok": False, "status": "verification_failed", "final_commit": final_commit,
                "message": "Git completed but the final commit did not match the verified upstream commit. Review the checkout before running it."}
    return {"ok": True, "status": "updated", "previous_commit": state["current_commit"],
            "current_commit": final_commit, "branch": state["branch"],
            "message": "Dev Inspector was fast-forwarded to the verified upstream commit."}


def recent_changes(repo_path: Path | str | None = None) -> dict[str, Any]:
    """Return pending upstream changes when available, otherwise recent local commits."""
    state = check_for_updates(repo_path)
    if state.get("ok") and state.get("update_status") == "updates_available":
        return {**state, "change_scope": "upstream", "recent_changes": state.get("new_commits", [])}
    if state.get("ok"):
        root = Path(state["repo"])
    else:
        local = _context(repo_path)
        if not local.get("ok"):
            return state
        root = Path(local["repo"])
    log = _git(["log", "-5", "--oneline", "--decorate"], root)
    lines = _safe_log_lines(log.stdout) if _ok(log) else []
    result = dict(state)
    result["change_scope"] = "local"
    result["recent_changes"] = lines
    return result
