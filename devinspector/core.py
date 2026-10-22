"""Portable process and detection helpers."""
from __future__ import annotations
import os, platform, shutil, subprocess
from dataclasses import dataclass
from typing import Sequence

@dataclass
class CommandResult:
    available: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    error: str | None = None

def run(args: Sequence[str], timeout: float = 8, cwd: str | None = None) -> CommandResult:
    if not args or not shutil.which(args[0]):
        return CommandResult(False, error=f"Command not found: {args[0] if args else ''}")
    try:
        p = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
        return CommandResult(True, p.stdout.strip(), p.stderr.strip(), p.returncode)
    except (OSError, subprocess.TimeoutExpired) as e:
        return CommandResult(True, error=str(e))

def command_info(name: str, version_args: Sequence[str] = ("--version",)) -> dict:
    path = shutil.which(name)
    if not path: return {"status":"missing", "path":None, "version":None}
    r = run([path, *version_args])
    return {"status":"installed" if r.returncode == 0 else "partially detected", "path":path,
            "version":(r.stdout or r.stderr).splitlines()[0] if (r.stdout or r.stderr) else None}

def system_info() -> dict:
    uname = platform.uname()
    info = {"os":platform.system(), "distribution":platform.platform(), "release":platform.release(),
            "kernel":uname.version, "architecture":platform.machine(), "processor":platform.processor() or "unavailable",
            "logical_cpus":os.cpu_count(), "hostname":platform.node(), "user":os.environ.get("USER") or os.environ.get("USERNAME"),
            "cwd":os.getcwd(), "python":platform.python_version(), "shell":os.environ.get("SHELL") or os.environ.get("COMSPEC"),
            "terminal":os.environ.get("TERM"), "environment":{k:os.environ.get(k) for k in ("TERMUX_VERSION","CODESPACES","WSL_DISTRO_NAME","GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN","COLAB_RELEASE_TAG") if os.environ.get(k)}}
    try:
        import shutil as _s
        usage = _s.disk_usage(os.getcwd())
        info["storage"] = {"total_bytes":usage.total,"used_bytes":usage.used,"free_bytes":usage.free}
    except OSError: info["storage"] = {"status":"unavailable"}
    # Avoid external dependencies; Linux memory data only when readable.
    try:
        with open('/proc/meminfo', encoding='utf-8') as f:
            mem = dict(line.split(':',1) for line in f if ':' in line)
        info['memory_kib'] = {k:int(mem[k].strip().split()[0]) for k in ('MemTotal','MemAvailable') if k in mem}
    except (OSError, ValueError): info['memory_kib'] = {"status":"unavailable"}
    return info

LANGUAGES = {
 'Python': [('python3',['--version']),('python',['--version'])], 'Node.js':[('node',['--version'])],
 'TypeScript':[('tsc',['--version'])], 'Java':[('java',['-version'])], 'Go':[('go',['version'])],
 'Rust':[('rustc',['--version'])], 'PHP':[('php',['--version'])], 'Ruby':[('ruby',['--version'])],
 '.NET':[('dotnet',['--version'])], 'C/C++':[('cc',['--version']),('c++',['--version'])],
 'Kotlin':[('kotlinc',['-version'])], 'Swift':[('swift',['--version'])], 'Dart':[('dart',['--version'])],
 'R':[('R',['--version'])], 'Perl':[('perl',['--version'])]}
TOOLS = ['git','gh','docker','podman','npm','pnpm','yarn','bun','pipx','poetry','uv','conda','make','cmake','ninja','ssh','curl','wget','jq','terraform','wrangler','psql','mysql','redis-cli','aws','az','gcloud']

def detect_languages() -> dict:
    found={}
    for language, candidates in LANGUAGES.items():
        hits=[]
        for executable, args in candidates:
            data=command_info(executable,args)
            if data['status'] != 'missing': hits.append({"executable":executable,**data})
        if hits: found[language]=hits
    return found

def detect_tools() -> dict:
    return {name:command_info(name) for name in TOOLS if shutil.which(name)}
