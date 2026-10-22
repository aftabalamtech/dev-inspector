# Developer Diagnostics Toolkit

An interactive Python CLI for inspecting your current development environment: OS and hardware details, installed languages and tools, Python/Node.js packages, Git/GitHub state, Cloudflare Wrangler configuration, and common project files. It runs **on demand** and does not schedule jobs, upload reports, install software, or send telemetry.

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
| `4` | Check local Wrangler availability and show Wrangler configuration files in the current directory. |
| `5` | List detected developer tools and their paths/versions. |
| `6` | Inspect known project configuration files in the current directory. |
| `7` | Show PATH entries and environment variables, redacting values for sensitive variable names. |
| `8` | Write a local JSON and human-readable text diagnostic report. |
| `9` | Exit. |

For example, to inspect a project, open a terminal in that project directory, start the toolkit, and choose `6`. For a report, choose `8`, then enter a destination such as `./my-diagnostics.json`; the program writes that JSON file and a corresponding `./my-diagnostics.txt` file. Entering the default `./diagnostics-report.json` creates `diagnostics-report.json` and `diagnostics-report.txt` in the current directory. Existing report files are not overwritten; choose a new filename if prompted with a conflict.

Git operations that change repository state ask for confirmation. Review the destination branch/remote or staged diff before confirming. The toolkit does not offer force-push, reset, or branch deletion. Use menu option `0` in a submenu to return, or `9` in the main menu to exit.

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

Project inspection is limited to files in the current directory; `.env` contents are never read. Sensitive environment-variable values are redacted from the environment view. GitHub authentication output is reduced to a status. Wrangler checks are local and do not claim live Cloudflare account verification. Reports are written locally only.

The project has been exercised in a Linux sandbox. Windows, macOS, Termux, and cloud IDE behavior is designed to degrade gracefully but has not been verified on those systems.

## Extending the toolkit

Add executable detection in `devinspector/core.py`, inspection logic in `devinspector/inspectors.py`, and menu/report behavior in the corresponding modules. Keep scans scoped to relevant project files and never print secret values.
