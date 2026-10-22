"""Small, dependency-free terminal styling and aligned output helpers."""
from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from typing import TextIO

RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
BLUE = "\033[34m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
GRAY = "\033[90m"
WHITE = "\033[97m"


def color_supported(stream: TextIO | None = None) -> bool:
    """Return whether ANSI color is appropriate for this output stream."""
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR") or os.environ.get("TERM", "").lower() == "dumb":
        return False
    try:
        if not stream.isatty():
            return False
    except (AttributeError, OSError):
        return False
    if stream is sys.stdout:
        try:
            if not sys.stdin.isatty():
                return False
        except (AttributeError, OSError):
            return False
    if os.name == "nt":
        return bool(os.environ.get("WT_SESSION") or os.environ.get("ANSICON") or os.environ.get("ConEmuANSI") == "ON")
    return True


def paint(text: object, color: str, *, bold: bool = False, stream: TextIO | None = None) -> str:
    value = str(text)
    if not color_supported(stream):
        return value
    return f"{BOLD if bold else ''}{color}{value}{RESET}"


def status_label(text: object, *, stream: TextIO | None = None) -> str:
    value = str(text)
    lower = value.lower()
    if any(word in lower for word in ("not found", "missing", "failed", "error", "not authenticated")):
        return paint(value, RED, bold=True, stream=stream)
    if any(word in lower for word in ("installed", "authenticated", "success", "done", "ok")):
        return paint(value, GREEN, bold=True, stream=stream)
    if any(word in lower for word in ("unavailable", "unsupported", "warning", "partially", "redacted")):
        return paint(value, YELLOW, bold=True, stream=stream)
    return paint(value, WHITE, stream=stream)


def selection_menu(title: str, options: Mapping[str, str], *, stream: TextIO | None = None) -> str:
    rows = [heading(title, stream=stream)]
    rows.extend(menu_item(number, label, stream=stream) for number, label in options.items())
    return "\n".join(rows)


def heading(title: str, *, stream: TextIO | None = None) -> str:
    label = title.upper()
    bar = "─" * max(8, min(len(label), 58))
    return f"\n{paint(label, CYAN, bold=True, stream=stream)}\n{paint(bar, BLUE, stream=stream)}"


def banner(*, stream: TextIO | None = None) -> str:
    title = paint("DEV INSPECTOR", CYAN, bold=True, stream=stream)
    return f"\n{title}\n{paint('Cross-platform developer diagnostics', GRAY, stream=stream)}\n"


def _human_value(key: str, value: object) -> object:
    lowered = key.lower()
    if lowered in {"memtotal", "memavailable"} and isinstance(value, int):
        return f"{value / (1024 * 1024):.2f} GiB"
    if isinstance(value, int) and (lowered.endswith("_bytes") or lowered in {"total", "used", "free"}):
        number = float(value)
        for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
            if abs(number) < 1024 or unit == "TiB":
                return f"{number:.2f} {unit}" if unit != "B" else f"{number:.0f} B"
            number /= 1024
    if lowered.endswith("_kib") and isinstance(value, int):
        return f"{value / (1024 * 1024):.2f} GiB"
    if lowered in {"path", "cwd", "executable", "hostname", "user", "shell"} and value is not None:
        return str(value)
    return value


def _label(key: object) -> str:
    text = str(key).replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else ""


def _value_color(key: str, value: object) -> str:
    k = key.lower()
    v = str(value).lower()
    if any(part in k for part in ("path", "cwd", "executable", "directory")):
        return GRAY
    if any(part in v for part in ("not found", "missing", "failed", "error", "not authenticated")):
        return RED
    if any(part in v for part in ("unavailable", "unsupported", "warning", "partially", "redacted")):
        return YELLOW
    if any(part in v for part in ("installed", "authenticated", "success", "true")):
        return GREEN
    return WHITE


def _format_value(key: str, value: object, *, stream: TextIO | None = None) -> str:
    if value is None:
        value = "unavailable"
    if key.lower() == "installed" and isinstance(value, bool):
        value = "[INSTALLED]" if value else "[NOT FOUND]"
    if key.lower() == "status":
        lowered = str(value).lower()
        if lowered == "installed":
            value = "[INSTALLED]"
        elif lowered == "missing":
            value = "[NOT FOUND]"
        elif "partial" in lowered:
            value = "[WARN] Partially detected"
        elif lowered == "unsupported":
            value = "[WARN] Unsupported"
        elif lowered == "unavailable":
            value = "[WARN] Unavailable"
        elif lowered == "error":
            value = "[ERROR]"
    value = _human_value(key, value)
    if isinstance(value, bool):
        value = "Yes" if value else "No"
    if isinstance(value, (Mapping, list, tuple)):
        return ""
    return paint(value, _value_color(key, value), stream=stream)


def render(title: str, data: object, *, stream: TextIO | None = None) -> str:
    """Render nested structured results as aligned, colored terminal key/value rows."""
    lines = [heading(title, stream=stream)]

    def walk(value: object, indent: int = 0, parent: str = "") -> None:
        prefix = " " * indent
        if isinstance(value, Mapping):
            if not value:
                lines.append(prefix + paint("(none)", GRAY, stream=stream))
                return
            entries = list(value.items())
            width = min(max((len(_label(k)) for k, _ in entries if not isinstance(_, (Mapping, list, tuple))), default=0), 28)
            for key, item in entries:
                label = _label(key)
                if isinstance(item, (Mapping, list, tuple)):
                    lines.append(prefix + paint(label, MAGENTA, bold=True, stream=stream) + paint(":", GRAY, stream=stream))
                    walk(item, indent + 2, str(key))
                else:
                    label_out = paint(label.ljust(width), MAGENTA, stream=stream)
                    lines.append(f"{prefix}{label_out} {paint(':', GRAY, stream=stream)} {_format_value(str(key), item, stream=stream)}")
        elif isinstance(value, (list, tuple)):
            if not value:
                lines.append(prefix + paint("(none)", GRAY, stream=stream))
            for index, item in enumerate(value, 1):
                if isinstance(item, Mapping):
                    lines.append(prefix + paint(f"[{index}]", CYAN, bold=True, stream=stream))
                    walk(item, indent + 2, parent)
                else:
                    lines.append(prefix + paint("• ", CYAN, stream=stream) + _format_value(parent, item, stream=stream))
        else:
            lines.append(prefix + _format_value(parent, value, stream=stream))

    walk(data)
    return "\n".join(lines)


def menu_item(number: str, label: str, *, stream: TextIO | None = None) -> str:
    return f"{paint(f'[{number}]', CYAN, bold=True, stream=stream)} {paint(label, WHITE, bold=True, stream=stream)}"


def prompt_text(message: str, *, warning: bool = False, stream: TextIO | None = None) -> str:
    color = YELLOW if warning else CYAN
    return paint(message, color, bold=True, stream=stream)


def print_result(message: str, *, ok: bool | None = None, stream: TextIO | None = None) -> None:
    if ok is True:
        tag = paint("[OK]", GREEN, bold=True, stream=stream)
    elif ok is False:
        tag = paint("[ERROR]", RED, bold=True, stream=stream)
    else:
        tag = paint("[WARN]", YELLOW, bold=True, stream=stream)
    print(f"{tag} {message}", file=stream or sys.stdout)
