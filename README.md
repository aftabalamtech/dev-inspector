# Developer Diagnostics Toolkit

An interactive Python CLI for inspecting your current development environment: OS and hardware details, installed languages and tools, Python/Node.js packages, Git/GitHub state, Cloudflare `cf`/Wrangler/cloudflared tools, and common project files. It runs **on demand** and does not schedule jobs, upload reports, or send telemetry. Cloudflare install, update, uninstall, authentication, deployment, and tunnel operations require explicit confirmation.

## Requirements

- Python 3.10+ recommended (Python is the only required dependency).
- Git, GitHub CLI (`gh`), Wrangler, language runtimes, and package managers are optional; each feature is detected independently.
- No `pip install` is needed.

## Get the project and start it

Clone the public repository:

```sh
git clone https://github.com/aftabalamtech/dev-inspector.git
cd dev-inspector
```

Linux, macOS, WSL, Android Termux, or a Linux-based cloud IDE:

```sh
python3 main.py
```

Or use the included launcher on Unix-like systems:

```sh
chmod +x launch.sh   # only needed if execute permission was not preserved
./launch.sh
```

Windows PowerShell:

```powershell
git clone https://github.com/aftabalamtech/dev-inspector.git
Set-Location dev-inspector
py main.py
```

Or:

```powershell
.\launch.ps1
```

If `py` is not available on Windows, use `python main.py`. To check that Python is installed first, run `python --version` (Windows) or `python3 --version` (Linux/macOS).

## How to use the interactive menu

Start the program with one of the commands above. At the `Select:` prompt, enter the menu number and press Enter. The menu is:

| Number | Action |
| --- | --- |
| `1` | Show OS, architecture, CPU count, storage, available memory (where readable), runtime, and environment indicators. |
| `2` | Detect installed languages; enter `1` for Python interpreter/pip/package details or `2` for Node.js/package-manager/package details. |
| `3` | Show Git/GitHub status, then choose a Git action: `1` status, `2` fetch, `3` pull, `4` create/switch branch, `5` stage selected paths, `6` review staged changes, `7` commit, `8` push, `9` clone, or `0` back. |
| `4` | Open the Cloudflare Toolkit: install/use/update/uninstall Cloudflare `cf`, Wrangler, or cloudflared; inspect Workers/Pages, manage tunnels, and check authentication. Mutating actions require confirmation. |
| `5` | List detected developer tools and their paths/versions. |
| `6` | Inspect known project configuration files in the current directory. |
| `7` | Show PATH entries and environment variables, redacting values for sensitive variable names. |
| `8` | Write a local JSON and human-readable text diagnostic report. |
| `9` | Open the self-update manager to check, inspect, and optionally apply a Git-based update. |
| `0` | Exit. |

For example, to inspect a project, open a terminal in that project directory, start the toolkit, and choose `6`. For a report, choose `8`, then enter a destination such as `./my-diagnostics.json`; the program writes that JSON file and a corresponding `./my-diagnostics.txt` file. Entering the default `./diagnostics-report.json` creates `diagnostics-report.json` and `diagnostics-report.txt` in the current directory. Existing report files are not overwritten; choose a new filename if prompted with a conflict.

Git operations that change repository state ask for confirmation. Review the destination branch/remote or staged diff before confirming. The toolkit does not offer force-push, reset, or branch deletion. Use menu option `0` in a submenu to return; `0` in the main menu exits.

## Self-updating Dev Inspector

Clone the repository once using the instructions above, then launch it normally. Choose main-menu option `9` to open **DEV INSPECTOR UPDATE MANAGER**:

- `1` checks the verified upstream, shows pending commits and a diff summary, then asks before applying an update.
- `2` checks for updates without changing application files (Git's remote-tracking metadata is refreshed).
- `3` shows the installed version/commit, branch, and working-tree status from Git metadata.
- `4` shows available upstream commits or recent local commit messages.
- `0` returns to the main menu.

Self-update is supported for a Git checkout whose configured branch upstream points to `https://github.com/aftabalamtech/dev-inspector` (HTTPS or GitHub SSH remotes are accepted). It requires Git, network access, and a configured upstream branch. The updater fetches only that branch, checks the repository identity and commit ancestry, and applies updates only as a fast-forward after confirmation. It refuses dirty working trees, local/upstream divergence, mismatched remotes, or unverifiable fetches. Fetch/merge hooks are disabled for the update operation, and Git is instructed not to overwrite ignored files. It never runs `git reset --hard` or `git clean`, stashes or discards changes, or installs dependencies; review and resolve local work yourself before retrying. Restart the application after a successful update.

If you installed from a ZIP/archive or another non-Git copy, the built-in updater will explain that it cannot update that installation. Install a Git clone separately instead of cloning over or deleting the existing folder:

```sh
git clone https://github.com/aftabalamtech/dev-inspector.git
cd dev-inspector
python3 main.py
```

On Windows PowerShell, use `py main.py` from the newly cloned directory. Back up and manually carry over any personal files; the updater does not merge arbitrary files from archive installations.

See [Cloudflare Toolkit usage, supported installation methods, safety behavior, and official documentation links](docs/cloudflare-toolkit.md) for details. Automatic `cloudflared` installation is deliberately unavailable on Termux/Android because Cloudflare's documented installation methods do not specify Termux support.

## Terminal colors

The interface uses ANSI colors in supported interactive terminals, including Android Termux, Linux/macOS terminals, Windows Terminal, Codespaces, and IDX. Colors are automatically disabled when output is redirected or the terminal is non-interactive. Set `NO_COLOR` to disable colors explicitly:

```sh
NO_COLOR=1 python3 main.py
```

For example, piping output to a file or another command automatically uses plain text:

```sh
python3 main.py | tee session.log
```

No third-party color package is required.

## Tests

From the cloned `dev-inspector` directory, run:

```sh
python3 -m unittest discover -s tests -v
```

On Windows, run:

```powershell
py -m unittest discover -s tests -v
```

## Capabilities, safety, and limitations

System details use Python's standard library and `/proc/meminfo` where readable. Memory and hardware details may be unavailable on Windows/macOS or restricted environments. Executable availability is used for language/tool detection. Python and Node.js have package inspectors; other detected languages currently show version and executable information rather than a full package inspector.

Project inspection is limited to files in the current directory; `.env` contents are never read. Sensitive environment-variable values are redacted from the environment view. GitHub and Wrangler authentication output is reduced to a status. Diagnostic reports are local only. For supported Cloudflare operations and limitations, see [the Cloudflare Toolkit guide](docs/cloudflare-toolkit.md).

The project has been exercised in a Linux sandbox. Windows, macOS, Termux, and cloud IDE behavior is designed to degrade gracefully but has not been verified on those systems.

## Extending the toolkit

Add executable detection in `devinspector/core.py`, inspection logic in `devinspector/inspectors.py`, and menu/report behavior in the corresponding modules. Keep scans scoped to relevant project files and never print secret values.
