"""Offline release checks. Reports filenames and key names, never secret values."""
import ast
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parent


def main():
    run=lambda *args: subprocess.run(['git',*args],cwd=ROOT,check=True,capture_output=True,text=True).stdout
    files=set(run('ls-files').splitlines())
    files.update(run('ls-files','--others','--exclude-standard').splitlines())
    problems=[]; parsed=0
    credential_files={'config.json','config.local.json','client_secret.json','yt_token.pickle','token.json'}
    for name in sorted(files):
        path=ROOT/name
        if not path.is_file(): continue
        if Path(name).name in credential_files: problems.append(name+': credential file included')
        if path.stat().st_size > 50*1024*1024: problems.append(name+': exceeds 50 MB review limit')
        if path.suffix in ('.mp4','.wav','.m4a'): problems.append(name+': generated media included')
        if path.suffix not in ('.py','.json','.yml','.yaml','.md','.txt','.jsonl'): continue
        text=path.read_text(encoding='utf-8-sig')
        if path.suffix=='.py':
            try: ast.parse(text); parsed+=1
            except SyntaxError: problems.append(name+': Python syntax error')
        # Familiar provider tokens plus secret-bearing JSON fields; no values are printed.
        if re.search(r'AIza[0-9A-Za-z_-]{30,}|gh[pousr]_[0-9A-Za-z]{30,}|AQ\.[0-9A-Za-z_-]{35,}',text):
            problems.append(name+': credential-shaped text')
        if path.suffix=='.json' and path.name.startswith('config'):
            cfg=json.loads(text)
            for key,value in cfg.items():
                if key.startswith('_NOTE_'): continue
                if any(k in key.lower() for k in ('api_key','token','secret','webhook')):
                    values=value if isinstance(value,list) else [value]
                    if any(v and not any(marker in str(v).upper() for marker in ('PASTE_','_HERE','YOUR_')) for v in values):
                        problems.append(name+': nonempty '+key)
    report={'python_files_parsed':parsed,'files_considered':len(files),'problems':problems,
            'scope':'Offline working-tree/index scan; not a complete secret detector or history scan.'}
    print(json.dumps(report,indent=2))
    return bool(problems)

if __name__=='__main__': sys.exit(main())
