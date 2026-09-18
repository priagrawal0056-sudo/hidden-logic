"""Explicit editorial decisions, separate from source retrieval and model scores."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from credible.core import digest, now

path = Path('research/reviews.json')
reviews = json.loads(path.read_text(encoding='utf-8'))
# Replace a unit-price explanation already present in the authored reserve.
lines = Path('research/shopping.txt').read_text(encoding='utf-8').splitlines()
lines[17] = ('Why a shop weighing scale has a tiny level indicator|'
    'Tilting some portable weighing scales changes their accuracy, so a level indicator helps establish the intended operating position.|'
    'Animate a scale platform tilting beside its level indicator; label the reading as an illustrative example.|nist.gov')
Path('research/shopping.txt').write_text('\n'.join(lines)+'\n', encoding='utf-8')
url='https://nvlpubs.nist.gov/nistpubs/hb/2019/NIST.HB.44-2019.pdf'
doc=json.loads((Path('research/cache')/(digest(url)[:20]+'.json')).read_text(encoding='utf-8'))
quote='a portable scale shall be equipped with level-indicating means if its weighing performance is changed'
assert quote in doc['text']
reviews['shopping-018']={
    'sources':[{'url':url,'publisher':'nist.gov','passage':quote,'retrieved_at':doc['retrieved_at']}],
    'scope':'NIST Handbook 44 (2019) portable-scale design example where tilt affects accuracy; not a statement of current law everywhere.',
    'region':'United States design-standard example', 'evidence_status':'reviewed',
    'support_review':{'method':'Editorial comparison with the complete level-indicator provision',
                      'reviewed_at':now().isoformat(), 'finding':lines[17].split('|')[1]},
    'editorial_scores':dict(recognition=3,overlooked_detail=4,payoff=3,evidence=3,visuals=4)}

novelty={
 'home-003':'The resistance changes immediately after closing, although the same door and seal are being used.',
 'home-015':'Two metal pans on the same hob can behave differently because being metal is not the whole requirement.',
 'buildings-001':'The cuts are deliberate weak lines: a controlled crack can be part of the design.',
 'buildings-003':'A gap that looks like unfinished masonry can be a planned path for trapped water.',
 'buildings-007':'Condensation on the outside can have a different meaning from moisture between the panes.',
 'buildings-011':'Turning sunglasses can reveal a pattern already hidden in apparently clear glass.',
 'buildings-029':'A crossing can communicate through a moving part most sighted pedestrians never notice.',
 'buildings-033':'An empty lift can be positioning itself for a passenger who has not called it yet.',
 'buildings-064':'A shiny layer pressed against another surface loses the air-space condition that makes it a radiant barrier.',
 'buildings-066':'The air temperature can stay the same while your comfort changes beside the window.',
 'technology-003':'The visible camera jump can be a switch to a different lens rather than a failed attempt to focus.',
 'technology-016':'A droplet changes the electrical measurement, so the screen must distinguish liquid from a finger.',
 'technology-022':'Matching plugs conceal different current capabilities inside the cable.',
 'food-015':'Graininess can be a physical change in sugar crystals rather than a sign of spoilage.',
 'food-018':'A pale surface can come from a change in the chocolate itself, not a coating added by the maker.',
 'packaging-001':'The tiny valve lets the bag release gas without behaving like a permanently open hole.',
 'packaging-011':'The container can move its own floor instead of pulling cream through a conventional dip tube.',
 'packaging-017':'A bottle panel that looks dented can be designed to move during cooling.',
 'shopping-003':'The receipt can show unfamiliar digits even though you paid from the expected card account.',
 'shopping-018':'The small level belongs to the measurement system, not just the shop counter.',
 'clothing-001':'Lifting the pull tab does more than give your fingers something to grip: it releases the lock.',
 'clothing-010':'Blue outside and white inside can come from how the same fabric is woven.',
 'clothing-029':'Walking can repeatedly load and pull the knot, even if you never touch the laces.',
 'clothing-035':'A car windscreen can filter the light that normally triggers the lenses outdoors.'}
for tid, value in novelty.items():
    if tid in reviews:
        reviews[tid]['novelty']=value
        reviews[tid]['editorial_scores']['overlooked_detail']=4
        reviews[tid]['editorial_scores']['payoff']=4
# Accurate sources do not automatically make an interesting episode.
for tid in ('home-019','home-025','buildings-015','clothing-017','clothing-026'):
    reviews[tid]['editorial_scores']['payoff']=1
    reviews[tid]['editorial_note']='Hold: the current angle mainly explains obvious utility; needs a less familiar mechanism before selection.'
path.write_text(json.dumps(reviews,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Reviewed:',len(reviews),'editorial holds:',sum(min(r['editorial_scores'].values())<2 for r in reviews.values()))
