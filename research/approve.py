"""Apply explicit editorial decisions to retrieved source passages.

This is deliberately not called by search or ranking: a matching string alone
does not establish causal support.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from credible.core import digest,now

def approve(decisions_path):
    packets={r['topic_id']:r for r in json.loads(Path('research/review-packets.json').read_text(encoding='utf-8'))}
    path=Path('research/reviews.json')
    reviews=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    for line in Path(decisions_path).read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'): continue
        fields=line.split('|')
        tid,quote,scope=fields[:3]
        p=dict(packets[tid])
        if len(fields)>6:
            p.update(url=fields[5],publisher=fields[6])
        doc=json.loads((Path('research/cache')/(digest(p['url'])[:20]+'.json')).read_text(encoding='utf-8'))
        assert quote.casefold() in doc['text'].casefold(),(tid,'passage not found')
        assert len(quote.split())<=25,(tid,'quote too long')
        reviews[tid]={'sources':[{'url':p['url'],'publisher':p['publisher'],'passage':quote,
                                 'retrieved_at':doc['retrieved_at']}],
            'scope':scope,'region':'United States (ADA/ABA example)' if p['publisher']=='access-board.gov' else
                     'United Kingdom example' if p['publisher']=='gov.uk' else 'Global where the specified design is used',
            'evidence_status':'reviewed',
            'support_review':{'reviewed_at':now().isoformat(),'method':'Editorial comparison of stated mechanism with retrieved primary text',
                              'finding':p['claim'],'scope':scope},
            'editorial_scores':{'recognition':3,'overlooked_detail':3,'payoff':3,'evidence':3,'visuals':3}}
        if len(fields)>3 and fields[3]:
            reviews[tid]['claim']=fields[3]
            reviews[tid]['support_review']['finding']=fields[3]
        if len(fields)>4 and fields[4]:
            reviews[tid]['title']=fields[4]
            reviews[tid]['observation']=fields[4].removeprefix('Why ')
    path.write_text(json.dumps(reviews,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Source-reviewed briefs:',len(reviews))

if __name__=='__main__': approve(sys.argv[1])
