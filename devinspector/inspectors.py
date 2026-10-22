"""Language, project, Git and Cloudflare inspection helpers."""
from __future__ import annotations
import json, os
from pathlib import Path
from .core import run

SECRET_MARKERS=('TOKEN','SECRET','PASSWORD','PASSWD','PRIVATE','API_KEY','CREDENTIAL')
def redact_env_names() -> list[str]:
    return sorted(k for k in os.environ if any(x in k.upper() for x in SECRET_MARKERS))

def python_details() -> dict:
    import sys
    r=run([sys.executable,'-m','pip','list','--format=json'],timeout=20)
    packages=[]
    if r.returncode==0:
        try: packages=json.loads(r.stdout)
        except json.JSONDecodeError: pass
    pip=run([sys.executable,'-m','pip','--version'])
    return {"interpreter":sys.executable,"version":sys.version.split()[0],"pip":pip.stdout if pip.returncode==0 else pip.error or pip.stderr,"packages":packages}

def node_details(project: Path | None = None) -> dict:
    managers={}
    for cmd in ('npm','npx','corepack','pnpm','yarn','bun'):
        r=run([cmd,'--version'])
        if r.available and r.returncode==0: managers[cmd]=r.stdout or r.stderr
    global_pkgs={}
    if 'npm' in managers:
        r=run(['npm','list','-g','--depth=0','--json'],timeout=20)
        if r.returncode==0:
            try: global_pkgs=json.loads(r.stdout).get('dependencies',{})
            except json.JSONDecodeError: pass
    local={}
    if project:
        p=project/'package.json'
        if p.is_file():
            try: local=json.loads(p.read_text(encoding='utf-8'))
            except (OSError,json.JSONDecodeError): local={"error":"Could not parse package.json"}
    return {"managers":managers,"global_packages":global_pkgs,"project":local}

def git_details(cwd: str | None = None) -> dict:
    result={}
    for key,args in {'version':['git','--version'],'status':['git','status','--short','--branch'],'branch':['git','branch','--show-current'],'remotes':['git','remote','-v'],'recent_commits':['git','log','-5','--oneline']}.items():
        r=run(args,cwd=cwd); result[key]=r.stdout if r.available and r.returncode==0 else (r.error or r.stderr or 'unavailable')
    gh=run(['gh','auth','status'],cwd=cwd)
    result['github_auth']='authenticated (details omitted)' if gh.returncode==0 else 'not authenticated or unavailable'
    return result

def cloudflare_details(cwd: Path) -> dict:
    r=run(['wrangler','--version'],cwd=str(cwd))
    configs=[p.name for p in cwd.iterdir() if p.name in ('wrangler.toml','wrangler.json','wrangler.jsonc')]
    return {"wrangler":r.stdout if r.returncode==0 else (r.error or 'unavailable'),"config_files":configs,"live_account_verified":False}

def inspect_project(cwd: Path) -> dict:
    known={'package.json','pyproject.toml','requirements.txt','Pipfile','poetry.lock','uv.lock','Cargo.toml','go.mod','pom.xml','build.gradle','Dockerfile','docker-compose.yml','compose.yaml','wrangler.toml','wrangler.json','wrangler.jsonc','.gitignore','.env.example'}
    files=sorted(p.name for p in cwd.iterdir() if p.name in known)
    data={"directory":str(cwd),"files":files,"secret_environment_variable_names":redact_env_names(),"findings":[]}
    p=cwd/'package.json'
    if p.is_file():
        try:
            pkg=json.loads(p.read_text(encoding='utf-8')); data['package']={k:pkg.get(k,{}) for k in ('name','scripts','dependencies','devDependencies')}
        except (OSError,json.JSONDecodeError): data['findings'].append('package.json is unreadable or invalid JSON')
    if (cwd/'.env').exists(): data['findings'].append('.env exists; contents intentionally not read')
    return data
