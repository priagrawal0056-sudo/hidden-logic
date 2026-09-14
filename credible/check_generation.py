"""Optional integration check. Reads an existing local key without copying/logging it."""
import argparse
import os
from pathlib import Path
from .core import read,save
from .evidence import FreeModel, generate_episode
from .pipeline import settings
from .quality import script_checks

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--local-config');args=parser.parse_args()
    if args.local_config:
        os.environ['HL_GEMINI_API_KEY']=read(args.local_config,{}).get('gemini_api_key','')
    model=FreeModel(settings()); model.remaining=2
    docs=[read(p) for p in Path('outputs/credible/evidence').glob('*.json')]
    docs={d['url']:d for d in docs if d['publisher'] in ('UK CMA','GS1')}
    try:
        episode=generate_episode(model,docs,read('outputs/credible/reserve.json',[]),'demonstration_first')
        script_checks(episode)
        save('outputs/generation-check.json',{'status':'passed','episode':episode})
        print('Live grounded generation passed:',episode['title'])
    except Exception as exc:
        save('outputs/generation-check.json',{'status':'unavailable_or_rejected','error':str(exc)[:180]})
        print('Live generation check:',str(exc)[:180])

if __name__=='__main__':main()
