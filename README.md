# Developer Diagnostics Toolkit

A Python, standard-library-first interactive CLI for inspecting the current development environment, installed languages/tools, Git state, Cloudflare Wrangler configuration, and common project files. It is **on-demand only**: it does not schedule jobs, upload reports, install software, or send telemetry.

## Requirements and launch

- Python 3.10+ recommended; Python itself is required.
- Git, GitHub CLI, Wrangler, language runtimes and package managers are detected independently and remain optional.
- Linux/macOS/WSL/Termux/cloud IDEs: `./launch.sh` or `python3 main.py`.
- Windows PowerShell: `./launch.ps1` or `py main.py`.
- No third-party package installation is required.

## Capabilities and limitations

System details use Python's standard library and `/proc/meminfo` where readable. Memory/hardware details can be unavailable on Windows/macOS or restricted environments. Language and tools are detected by executable availability; the Python and Node.js inspectors include package information. Other detected languages currently show version/executable information rather than a full package inspector. Project inspection is limited to files in the current directory and never reads `.env` contents. Git actions use the installed Git executable and confirm changes that modify repository state; no force-push or destructive reset/delete operations are offered. GitHub auth output is reduced to a status. Wrangler is checked locally; no live account claims are made. Reports are local JSON and text, and existing output files are never overwritten.

The toolkit has been exercised only in the current Linux sandbox. Windows/macOS/Termux/cloud IDE behavior is designed to degrade gracefully but has not been verified on those systems. Shell launchers and platform-specific hardware commands are intentionally kept minimal.

## Development

Run tests from this directory:

```sh
python3 -m unittest discover -s tests -v
```

Add detectors in `devinspector/core.py`, inspectors in `devinspector/inspectors.py`, and menu/report behavior in the corresponding modules. Never add output of secret values; redact sensitive values and restrict project scanning to relevant paths.
