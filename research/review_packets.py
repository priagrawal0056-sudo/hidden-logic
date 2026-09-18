import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from credible.core import digest
from research.collect import candidates

STOP=set('why your a an the to in on of and or for from with can some their its this that it is as by at when while than not into more are have has be after before through these those each all one'.split())
def words(t): return {w[:5] for w in re.findall('[a-z]{3,}',t.lower()) if w not in STOP}

def packets():
    path=max(Path('research').glob('search-results-*.json'),key=lambda p:int(p.stem.rsplit('-',1)[1]))
    rows=json.loads(path.read_text(encoding='utf-8'))
    freq=Counter(w for r in rows for w in words(r['claim']+' '+r['title']))
    result=[]
    for row in rows:
        query=words(row['claim']+' '+row['title']); ranked=[]
        for source in candidates(row):
            p=Path('research/cache')/(digest(source['url'])[:20]+'.json')
            if not p.exists(): continue
            doc=json.loads(p.read_text(encoding='utf-8'))
            text=doc['text']
            for match in re.finditer(r'[^.!?]+[.!?]?',text):
                start=max(0,match.start()); snippet=text[start:start+450]
                overlap=query&words(snippet)
                weight=sum(math.log((len(rows)+1)/(freq[w]+1)) for w in overlap)
                weight+=sum(3 for a,b in zip(row['claim'].lower().split(),row['claim'].lower().split()[1:])
                            if a not in STOP and b not in STOP and a+' '+b in snippet.lower())
                if len(overlap)>=3: ranked.append((weight,source,doc,snippet))
        ranked.sort(key=lambda v:-v[0])
        best=ranked[0] if ranked else None
        result.append({'topic_id':f"{row['category']}-{row['index']:03d}", 'title':row['title'],'claim':row['claim'],
            'url':best[1]['url'] if best else None,'publisher':row['domain'],
            'retrieved_at':best[2]['retrieved_at'] if best else None,
            'passage':best[3] if best else None})
    Path('research/review-packets.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

if __name__=='__main__':
    rows=packets()
    start=int(sys.argv[1]) if len(sys.argv)>1 else 0
    count=int(sys.argv[2]) if len(sys.argv)>2 else 20
    print(json.dumps(rows[start:start+count],ensure_ascii=True))
