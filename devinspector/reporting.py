import json
from pathlib import Path

def write_report(data: dict, destination: str) -> tuple[str,str]:
    path=Path(destination).expanduser()
    if path.exists(): raise FileExistsError(f"Refusing to overwrite existing report: {path}")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    text=path.with_suffix('.txt')
    if text.exists():
        path.unlink(); raise FileExistsError(f"Refusing to overwrite existing report: {text}")
    lines=["Developer Diagnostics Report", "="*28]
    for section, content in data.items():
        lines += ['', section.replace('_',' ').title(), '-'*len(section)]
        lines += [json.dumps(content,indent=2,ensure_ascii=False)]
    text.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return str(path),str(text)
