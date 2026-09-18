"""Compile human-authored briefs and explicit research reviews, never infer support from search rank."""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from credible.core import digest, duplicate, now
from credible.topics import validate_bank, evidence_ready, shortlist, LEGACY_PILLARS
from research.collect import candidates

NAMES={'home':'Home and household objects','buildings':'Buildings and public spaces',
       'technology':'Everyday technology','food':'Food and drink','packaging':'Packaging and materials',
       'transport':'Transport and street systems','shopping':'Shopping and payments',
       'clothing':'Clothing and personal items'}
SUBJECTS={
    # Match the actual object before incidental examples (a fridge cooling milk,
    # a microwave door, or a spray bottle). These are spacing groups, not claims.
    'electric-kettle':r'\bkettle',
    'refrigerators':r'\bfridge|\brefrigerator', 'freezers':r'\bfreezer',
    'dishwashers':r'\bdishwasher', 'microwave-ovens':r'\bmicrowave',
    'rice-cookers':r'\brice cooker', 'pressure-cookers':r'\bpressure cooker',
    'toasters':r'\btoaster', 'ovens':r'^Why (?:the |an? |your |some )?oven\b',
    'robot-vacuums':r'\brobot vacuum', 'vacuum-cleaners':r'\bvacuum(?! pack)',
    'induction-hobs':r'\binduction',
    'fire-door-seal':r'fire door.*strip|intumescent',
    'door-handles':r'door handles?|door knobs?',
    'access-ramps':r'ramps have flat|ramp handrails|wheelchair ramp|accessible ramp',
    'tactile-paving':r'tactile paving|warning paving',
    'stair-nosings':r'stair.*strip|step.*strip',
    'drinking-fountains':r'drinking fountain', 'green-roofs':r'green roof|roof garden',
    'spray-bottles':r'spray bottle|trigger spray', 'dispensing-pumps':r'lotion pump|airless.*pump',
    'toilets':r'\btoilet', 'showers':r'\bshower', 'taps':r'\btap\b|\btaps\b|aerator',
    'drain-traps':r'\bdrain|\bsink.*(pipe|gurgle)',
    'heat-pumps':r'heat pump', 'air-conditioners':r'air conditioner',
    'dehumidifiers':r'dehumidifier', 'radiators':r'radiator',
    'thermostats':r'thermostat', 'room-fans':r'ceiling fan|\bfan cools',
    'mayonnaise':r'mayonnaise', 'cheese':r'cheese', 'yoghurt':r'yoghurt|yogurt',
    'knitted-t-shirt':r'T-shirt.*seam|side seam.*wash',
    'computer-mice':r'optical mice|\bmouse\b|Bluetooth mice',
    'eyewear':r'sunglasses|photochromic|spectacles',
    'drinking-glasses':r'drinking glass|cold glass|glass.*condensation',
    'aircraft-windows':r'(aircraft|airplane|passenger|aeroplane).*window',
    'architectural-glazing':r'glaz|window|glass.*(edge|door|building)|tempered glass',
    'elevators':r'elevator', 'escalators':r'escalator|moving walkway',
    'doors':r'\bdoor|\bhandle|threshold|push-bar', 'accessibility':r'\bramp|handrail|tactile|warning paving',
    'zippers':r'\bzip', 'bread':r'\bbread|loaf|dough', 'eggs':r'\begg|custard|mayonnaise',
    'chocolate':r'chocolate', 'sugar':r'\bsugar|caramel|sweet', 'milk':r'\bmilk|yoghurt|cheese',
    'tyres':r'\btyre|\btire', 'payments':r'\bpayment|\bcard|\bPIN|\brefund|receipt',
    'barcodes':r'barcode', 'washing-machines':r'washing machine|\bwasher|front-loader',
    'dryers':r'dryer|lint filter', 'charging':r'charg|\bUSB', 'displays':r'\bscreen|display|OLED|LCD',
    'camera':r'camera|\bphoto|selfie|autofocus', 'wifi':r'Wi-Fi|mesh network|buffers',
    'bottles':r'bottle|\bcap\b|jar lid', 'cans':r'\bcan |\bcans |pull tab',
    'packaging-paper':r'cardboard|paper bag|corrugated', 'cooking-pans':r'\bpan\b|\boil\b',
    'trains':r'\btrain|railway|\btrack|platform', 'aircraft':r'aircraft|aeroplane|airplane|\bwing|passenger window',
    'traffic-signals':r'traffic light|\bjunction|crossing|countdown', 'water-fixtures':r'\btap|\bsink|\bdrain|shower|toilet',
    'denim':r'denim|jeans', 'wool':r'wool', 'knitted-fabric':r'knitted|knit\b|jumper|ribbed cuff',
    'cotton-fabric':r'cotton', 'fleece':r'fleece', 'rain-jackets':r'rain jacket|waterproof jacket',
    'down-insulation':r'down jacket', 'shoe-soles':r'shoe.*(sole|foam|squeak)|sole.*groove',
    'shoelaces':r'shoelace|lace hole', 'umbrellas':r'umbrella',
    'e-readers':r'e-reader', 'qr-codes':r'QR code',
}


def subject(title):
    for name,pattern in SUBJECTS.items():
        if re.search(pattern,title,re.I): return name
    return re.sub(r'[^a-z0-9]+','-',title.lower()).strip('-').removeprefix('why-')


def apply_review(row, review):
    row = {**row, **review}
    row['claim_id'] = review.get('claim_id') or 'mechanism-' + digest(
        re.sub(r'\W+', ' ', row['claim'].casefold()).strip())[:16]
    row['subject'] = review.get('subject') or subject(row['title'])
    return row


def compile_bank():
    paths=list(Path('research').glob('search-results-*.json'))
    search=json.loads(max(paths,key=lambda p:int(p.stem.rsplit('-',1)[1])).read_text(encoding='utf-8')) if paths else json.loads(Path('research/source_candidates.json').read_text(encoding='utf-8'))
    # Keep reproducible URL leads without committing raw search-result page text.
    compact=[{**{k:r[k] for k in ('category','index','title','domain')},
              'sources':[{k:s[k] for k in ('url','publisher')} for s in candidates(r)]} for r in search]
    Path('research/source_candidates.json').write_text(json.dumps(compact,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    found={(r['category'],r['index']):r for r in search}
    reviews=json.loads(Path('research/reviews.json').read_text(encoding='utf-8')) if Path('research/reviews.json').exists() else {}
    bank=[]
    for category in NAMES:
        lines=Path('research',category+'.txt').read_text(encoding='utf-8').splitlines()
        for i,line in enumerate(lines,1):
            title,claim,demo,domain=line.split('|')
            tid=f'{category}-{i:03d}'
            entry=found.get((category,i),{'domain':domain})
            if entry.get('title')!=title or entry['domain']!=domain: entry={'domain':domain}
            sources=candidates(entry)
            # A proposed publisher is a research lead, never supporting evidence.
            sources=[{k:s[k] for k in ('url','publisher')} for s in sources[:3]] or [
                {'url':'https://'+domain+'/', 'publisher':domain, 'research_lead_only':True}]
            row={'topic_id':tid,'claim_id':tid+'-'+digest(claim)[:10], 'subject':subject(title),
                 'category':category,'pillar':LEGACY_PILLARS[category],'title':title, 'observation':title.removeprefix('Why '),
                 'claim':claim, 'novelty':claim,
                 'scope':'The specific product construction or system described by the primary source; not all designs.',
                 'region':'Global where this design is used; verify local requirements before naming a rule.',
                 'footage':'Film '+title.removeprefix('Why ')+'; start with the visible detail, then a different close-up of the same object.',
                 'demonstration':demo, 'sources':sources, 'evidence_status':'pending_review',
                 'support_review':None, 'editorial_scores':{'recognition':3,'overlooked_detail':3,'payoff':3,'evidence':0,'visuals':3}}
            # Revisions can change the explanation and the object. Identity must
            # describe the reviewed version, not the discarded research lead.
            row = apply_review(row, reviews.get(tid,{}))
            bank.append(row)
    validate_bank(bank)
    Path('credible/topics.json').write_text(json.dumps(bank,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    Path('docs').mkdir(exist_ok=True)
    fields=['topic_id','category','pillar','title','observation','claim','novelty','scope','region','footage',
            'demonstration','evidence_status','support_review','editorial_scores','editorial_note','sources','subject','claim_id']
    with Path('docs/TOPICS_500.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        writer.writerows({k:json.dumps(r.get(k),ensure_ascii=False) if isinstance(r.get(k),(dict,list)) else r.get(k,'') for k in fields} for r in bank)
    md=['# Hidden Logic: 500 everyday mysteries','',
        'Research status is explicit. Only source-reviewed briefs can enter generation. Working explanations in pending rows are hypotheses to verify, not publishable facts.', '']
    for category,name in NAMES.items():
        md += ['## '+name,'']
        for row in bank:
            if row['category']==category:
                md += [f"- **{row['topic_id']} — {row['title']}** ({row['evidence_status']})",
                       f"  - Explanation to establish: {row['claim']}",
                       f"  - Show: {row['demonstration']}",
                       f"  - Source: [{row['sources'][0]['publisher']}]({row['sources'][0]['url']})"]
        md.append('')
    Path('docs/TOPICS_500.md').write_text('\n'.join(md).rstrip()+'\n',encoding='utf-8')
    history=json.loads(Path('channel_index.json').read_text(encoding='utf-8'))
    for p in ('state/credible/production.json','state/credible/reserve.json'):
        if Path(p).exists():
            value=json.loads(Path(p).read_text(encoding='utf-8'))
            history+=list(value.get('slots',{}).values()) if isinstance(value,dict) else value
    conflicts=[{'topic_id':r['topic_id'],'reason':duplicate(r,history)} for r in bank if duplicate(r,history)]
    report={'at':now().isoformat(),'topics':len(bank),'categories':dict(Counter(r['category'] for r in bank)),
            'source_reviewed':sum(evidence_ready(r) for r in bank),'pending':sum(not evidence_ready(r) for r in bank),
            'editorial_holds':sum(evidence_ready(r) and min(r['editorial_scores'].values())<2 for r in bank),
            'complete_supported_bank':all(evidence_ready(r) and min(r['editorial_scores'].values())>=2 for r in bank),
            'history_records_checked':len(history),'cooldown_conflicts':conflicts,
            'semantic_history_review':'Required again by independent script review; lexical checks alone are not proof of distinct claims.',
            'eligible_shortlist':[r['topic_id'] for r in shortlist(bank,history)]}
    Path('docs/topic-bank-validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('cooldown_conflicts','semantic_history_review')},indent=2))


if __name__=='__main__': compile_bank()
