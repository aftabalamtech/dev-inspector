from __future__ import annotations
import json, os, sys
from pathlib import Path
from .core import system_info, detect_languages, detect_tools
from .inspectors import python_details,node_details,git_details,cloudflare_details,inspect_project
from .reporting import write_report

def show(title, data):
    print(f'\n=== {title} ===')
    print(json.dumps(data,indent=2,ensure_ascii=False,default=str))
def confirm(message): return input(message+' [y/N] ').strip().lower()=='y'

def git_action():
    cwd=os.getcwd()
    print('Git actions: 1 status  2 fetch  3 pull  4 create branch  5 stage files  6 review staged  7 commit  8 push  9 clone  0 back')
    c=input('Select: ').strip()
    if c=='1': show('Git status',git_details(cwd)); return
    if c in ('2','3'):
        if c=='2': args=['git','fetch','--all','--prune']
        else:
            if not confirm('Pull changes into the current branch?'): return
            args=['git','pull','--ff-only']
        r=__import__('devinspector.core',fromlist=['run']).run(args,cwd=cwd); print(r.stdout or r.stderr or r.error or 'Done')
    elif c=='4':
        name=input('New branch name: ').strip()
        if name and confirm(f'Create and switch to branch {name!r}?'):
            from .core import run
            r=run(['git','switch','-c',name],cwd=cwd); print(r.stdout or r.stderr or r.error or 'Done')
    elif c=='5':
        names=input('File paths to stage (space-separated): ').split()
        if names and confirm('Stage only these paths: '+', '.join(names)+'?'):
            from .core import run
            r=run(['git','add','--',*names],cwd=cwd); print(r.stdout or r.stderr or r.error or 'Done')
    elif c=='6':
        from .core import run
        r=run(['git','diff','--cached','--'],cwd=cwd); print(r.stdout or '(no staged diff)')
    elif c=='7':
        from .core import run
        d=run(['git','diff','--cached','--'],cwd=cwd); print(d.stdout or '(no staged diff)')
        msg=input('Commit message: ').strip()
        if msg and confirm('Commit the staged changes shown above?'):
            r=run(['git','commit','-m',msg],cwd=cwd); print(r.stdout or r.stderr or r.error or 'Done')
    elif c=='8':
        from .core import run
        branch=run(['git','branch','--show-current'],cwd=cwd).stdout
        remote=input('Destination remote [origin]: ').strip() or 'origin'
        if confirm(f'Push current branch {branch!r} to remote {remote!r}?'):
            r=run(['git','push',remote,branch],cwd=cwd); print(r.stdout or r.stderr or r.error or 'Done')
    elif c=='9':
        url=input('Repository URL: ').strip()
        if url and not url.startswith('-') and confirm(f'Clone {url!r} into the current directory?'):
            from .core import run
            r=run(['git','clone',url],timeout=120); print(r.stdout or r.stderr or r.error or 'Done')

def main():
    while True:
        print('\nDeveloper Diagnostics Toolkit')
        print('1 System information  2 Languages & packages  3 Git/GitHub  4 Cloudflare  5 Developer tools  6 Project inspector  7 PATH/environment names  8 Diagnostic report  9 Exit')
        c=input('Select: ').strip()
        try:
            if c=='1': show('System information',system_info())
            elif c=='2':
                show('Detected languages',detect_languages())
                print('Inspect: 1 Python  2 Node.js  0 back')
                sub=input('Select: ').strip()
                if sub=='1': show('Python',python_details())
                elif sub=='2': show('Node.js',node_details(Path.cwd()))
            elif c=='3': show('Git and GitHub',git_details()); git_action()
            elif c=='4': show('Cloudflare',cloudflare_details(Path.cwd()))
            elif c=='5': show('Developer tools',detect_tools())
            elif c=='6': show('Project configuration',inspect_project(Path.cwd()))
            elif c=='7':
                safe={k:('[REDACTED]' if any(x in k.upper() for x in ('TOKEN','SECRET','PASSWORD','PASSWD','PRIVATE','API_KEY','CREDENTIAL')) else v) for k,v in os.environ.items()}
                show('PATH and environment',{'PATH':os.environ.get('PATH','').split(os.pathsep),'variables':safe})
            elif c=='8':
                data={'system':system_info(),'languages':detect_languages(),'tools':detect_tools(),'git':git_details(),'cloudflare':cloudflare_details(Path.cwd()),'project':inspect_project(Path.cwd())}
                dest=input('Report base path [./diagnostics-report.json]: ').strip() or './diagnostics-report.json'
                try:
                    j,t=write_report(data,dest); print(f'Wrote {j} and {t}')
                except (OSError,ValueError) as e: print(f'Report not written: {e}')
            elif c=='9': return
            else: print('Choose a listed number.')
        except (KeyboardInterrupt,EOFError): print('\nReturning to menu.')
        except Exception as e: print(f'Inspection failed safely: {type(e).__name__}: {e}')

if __name__=='__main__': main()
