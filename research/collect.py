"""Local research helper; source candidates are NOT automatically editorial-approved."""
import concurrent.futures
import json
import re
import sys
import logging
from pathlib import Path
from urllib.parse import urlsplit
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path('.research_lib').resolve())]
from credible.evidence import retrieve
logging.getLogger('pypdf').setLevel(logging.ERROR)


def candidates(row):
    if 'sources' in row:
        return row['sources']
    found=[]
    for block in (row.get('search') or '').split('-'*80):
        match=re.search(r'\((https://[^\s]+)\)\s*\n',block)
        if match:
            url=match.group(1)
            host=urlsplit(url).netloc.lower()
            domain=row['domain']
            # A search result mentioning a publisher is not necessarily that publisher.
            if host==domain or host.endswith('.'+domain):
                found.append({'url':url,'publisher':domain,'snippet':block.split('\n',2)[-1][:2500]})
    return found[:3]


def fetch(source):
    try:
        doc=retrieve(source,Path('research/cache'))
        return source['url'],{'ok':True,'retrieved_at':doc['retrieved_at']}
    except Exception as exc:
        return source['url'],{'ok':False,'error':type(exc).__name__}


if __name__=='__main__':
    path=max(Path('research').glob('search-results-*.json'),key=lambda p:int(p.stem.rsplit('-',1)[1]))
    rows=json.loads(path.read_text(encoding='utf-8'))
    sources={s['url']:s for row in rows for s in candidates(row)}
    existing=json.loads(Path('research/retrievals.json').read_text()) if Path('research/retrievals.json').exists() else {}
    pending=[s for u,s in sources.items() if u not in existing]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(fetch,source) for source in pending]
        for i,future in enumerate(concurrent.futures.as_completed(futures)):
            url,result=future.result()
            existing[url]=result
            if i%20==0:
                Path('research/retrievals.json').write_text(json.dumps(existing),encoding='utf-8')
                print(f'Retrieved {i+1}/{len(pending)} new source pages',flush=True)
    Path('research/retrievals.json').write_text(json.dumps(existing),encoding='utf-8')
    print(json.dumps({'sources':len(existing),'accessible':sum(v['ok'] for v in existing.values())}))
