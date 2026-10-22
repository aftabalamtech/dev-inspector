from __future__ import annotations

import os
from pathlib import Path

from .core import detect_languages, detect_tools, run, system_info
from .cloudflare_ui import cloudflare_menu
from .inspectors import cloudflare_details, git_details, inspect_project, node_details, python_details
from .reporting import write_report
from .ui import banner, menu_item, print_result, prompt_text, render, selection_menu


def show(title: str, data: object) -> None:
    print(render(title, data))


def ask(message: str, *, warning: bool = False) -> str:
    return input(prompt_text(message, warning=warning) + " ").strip()


def confirm(message: str) -> bool:
    return ask(message + " [y/N]", warning=True).lower() == "y"


def command_result(label: str, result) -> None:
    output = result.stdout or result.stderr or result.error or "Command completed without output."
    succeeded = result.available and result.returncode == 0 and result.error is None
    print_result(f"{label}: {output}", ok=succeeded)


def show_git_menu() -> None:
    print(selection_menu("Git Actions", {
        "1": "Check repository status",
        "2": "Fetch remote updates",
        "3": "Pull changes",
        "4": "Create and switch branch",
        "5": "Stage selected files",
        "6": "Review staged changes",
        "7": "Commit staged changes",
        "8": "Push current branch",
        "9": "Clone a repository",
        "0": "Return to previous menu",
    }))


def git_action() -> None:
    cwd = os.getcwd()
    show_git_menu()
    choice = ask("Select:")
    if choice == "1":
        show("Git Status", git_details(cwd))
    elif choice in ("2", "3"):
        if choice == "3" and not confirm("Pull changes into the current branch?"):
            print_result("Pull cancelled.")
            return
        args = ["git", "fetch", "--all", "--prune"] if choice == "2" else ["git", "pull", "--ff-only"]
        command_result("Fetch" if choice == "2" else "Pull", run(args, cwd=cwd))
    elif choice == "4":
        name = ask("New branch name:")
        if name and confirm(f"Create and switch to branch {name!r}?"):
            command_result("Create branch", run(["git", "switch", "-c", name], cwd=cwd))
    elif choice == "5":
        names = ask("File paths to stage (space-separated):").split()
        if names and confirm("Stage only these paths: " + ", ".join(names) + "?"):
            command_result("Stage files", run(["git", "add", "--", *names], cwd=cwd))
    elif choice == "6":
        result = run(["git", "diff", "--cached", "--"], cwd=cwd)
        if result.returncode == 0 and result.stdout:
            show("Staged Changes", {"diff": result.stdout})
        elif result.returncode == 0:
            print_result("No staged changes.")
        else:
            command_result("Review staged changes", result)
    elif choice == "7":
        diff = run(["git", "diff", "--cached", "--"], cwd=cwd)
        if diff.stdout:
            show("Staged Changes", {"diff": diff.stdout})
        else:
            print_result("No staged changes to commit.")
        message = ask("Commit message:")
        if message and confirm("Commit the staged changes shown above?"):
            command_result("Commit", run(["git", "commit", "-m", message], cwd=cwd))
    elif choice == "8":
        branch_result = run(["git", "branch", "--show-current"], cwd=cwd)
        branch = branch_result.stdout
        remote = ask("Destination remote [origin]:") or "origin"
        if confirm(f"Push current branch {branch!r} to remote {remote!r}?"):
            command_result("Push", run(["git", "push", remote, branch], cwd=cwd))
    elif choice == "9":
        url = ask("Repository URL:")
        if url and not url.startswith("-") and confirm(f"Clone {url!r} into the current directory?"):
            command_result("Clone", run(["git", "clone", url], timeout=120))
    elif choice != "0":
        print_result("Choose a listed number.", ok=False)


def show_main_menu() -> None:
    print("\n" + menu_item("1", "System Information"))
    print(menu_item("2", "Languages & Packages"))
    print(menu_item("3", "Git & GitHub"))
    print(menu_item("4", "Cloudflare Toolkit"))
    print(menu_item("5", "Developer Tools"))
    print(menu_item("6", "Project Inspector"))
    print(menu_item("7", "Environment & PATH"))
    print(menu_item("8", "Diagnostic Report"))
    print(menu_item("9", "Exit"))


def main() -> None:
    print(banner())
    while True:
        show_main_menu()
        choice = ask("Select:")
        try:
            if choice == "1":
                show("System Information", system_info())
            elif choice == "2":
                show("Detected Languages", detect_languages())
                print(selection_menu("Language Inspectors", {"1": "Python", "2": "Node.js", "0": "Back"}))
                subchoice = ask("Select:")
                if subchoice == "1":
                    show("Python Inspector", python_details())
                elif subchoice == "2":
                    show("Node.js Inspector", node_details(Path.cwd()))
                elif subchoice != "0":
                    print_result("Choose a listed number.", ok=False)
            elif choice == "3":
                show("Git & GitHub", git_details())
                git_action()
            elif choice == "4":
                cloudflare_menu(Path.cwd())
            elif choice == "5":
                show("Developer Tools", detect_tools())
            elif choice == "6":
                show("Project Inspector", inspect_project(Path.cwd()))
            elif choice == "7":
                sensitive = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "PRIVATE", "API_KEY", "CREDENTIAL")
                environment = {
                    key: ("[REDACTED]" if any(marker in key.upper() for marker in sensitive) else value)
                    for key, value in os.environ.items()
                }
                show("Environment & PATH", {
                    "PATH": os.environ.get("PATH", "").split(os.pathsep),
                    "variables": environment,
                })
            elif choice == "8":
                data = {
                    "system": system_info(),
                    "languages": detect_languages(),
                    "tools": detect_tools(),
                    "git": git_details(),
                    "cloudflare": cloudflare_details(Path.cwd()),
                    "project": inspect_project(Path.cwd()),
                }
                destination = ask("Report base path [./diagnostics-report.json]:") or "./diagnostics-report.json"
                try:
                    json_path, text_path = write_report(data, destination)
                    print_result(f"Reports written: {json_path} and {text_path}", ok=True)
                except (OSError, ValueError) as exc:
                    print_result(f"Report not written: {exc}", ok=False)
            elif choice == "9":
                print_result("Goodbye.", ok=True)
                return
            else:
                print_result("Choose a listed number.", ok=False)
        except (KeyboardInterrupt, EOFError):
            print_result("Returning to the main menu.")
        except Exception as exc:
            print_result(f"Inspection failed safely: {type(exc).__name__}: {exc}", ok=False)


if __name__ == "__main__":
    main()
