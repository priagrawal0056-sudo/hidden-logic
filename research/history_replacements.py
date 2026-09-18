"""Replace known/likely historical overlaps without resetting the legacy bank."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from credible.core import digest, now

REPLACEMENTS=[
 dict(topic_id='transport-055',
      title='Why some jet engines have a sawtooth edge',
      claim='Chevron nozzle edges change the mixing of hot core air and cooler fan air to reduce jet noise.',
      demonstration='Animate hot and cool flow meeting behind smooth and chevron edges; label the flow as an illustration, with no invented noise measurements.',
      footage='Use a licensed close-up of an engine with visible chevrons, then a distinct view of the same engine design.',
      novelty='The jagged edge is an acoustic design feature rather than decorative trim.',
      url='https://www.nasa.gov/aeronautics/nasa-helps-create-a-more-silent-night/',publisher='nasa.gov',
      passage='the shaped edges serve to smooth the mixing, which reduces turbulence that creates noise.',
      scope='Chevron-equipped turbofan designs; effectiveness depends on integration with the engine. No universal noise-reduction percentage.',
      reason='Replaces the window-hole explanation already published on 2026-06-28.'),
 dict(topic_id='technology-014',
      title='Why one video looks brighter than the buttons around it',
      claim='An HDR-capable display can render video highlights above standard interface white using available brightness headroom.',
      demonstration='Show a phone interface and video region on a labelled illustrative brightness scale; do not pretend the SDR Short reproduces actual HDR highlights.',
      footage='Use a phone close-up with an original neutral video interface, then a closer view of the picture beside its controls.',
      novelty='The screen can give a picture brighter highlights without giving every interface element the same brightness.',
      url='https://developer.apple.com/videos/play/wwdc2022/10113/',publisher='developer.apple.com',
      passage='values above 1 represent content brighter than SDR.',
      scope='Apple EDR on supported displays and apps with available headroom; output varies with device and brightness conditions.',
      reason='Replaces thermal screen dimming already covered by the channel on 2026-08-22.'),
 dict(topic_id='shopping-016',
      title='Why a cash total can round off while the card total does not',
      claim='Cash rounding can accommodate the available coins while electronic payments can still settle to the exact cent.',
      demonstration='Split a labelled Canadian example into a cash total and an exact electronic total; apply rounding to the final cash total, not every item.',
      footage='Film a neutral receipt beside coins and a card; use original illustrative amounts and remove real account details.',
      novelty='Changing the payment method can change the amount settled without changing any item price.',
      url='https://www.canada.ca/en/news/archive/2013/02/government-canada-royal-canadian-mint-bid-farewell-canadian-penny.html',publisher='canada.ca',
      passage='The phase-out of the penny will have no impact on cheque payments or electronic transactions.',
      scope='Canada penny phase-out guidance, documented in 2013; not a universal rule or a claim about every merchant today.',
      reason='Replaces likely overlap with the earlier self-checkout-freezing episode; full old script was unavailable.')]

path=Path('research/reviews.json')
reviews=json.loads(path.read_text(encoding='utf-8'))
for row in REPLACEMENTS:
    doc=json.loads((Path('research/cache')/(digest(row['url'])[:20]+'.json')).read_text(encoding='utf-8'))
    assert row['passage'] in doc['text'],row['topic_id']
    category,index=row['topic_id'].split('-')
    drafts=Path('research',category+'.txt')
    lines=drafts.read_text(encoding='utf-8').splitlines()
    lines[int(index)-1]='|'.join(row[k] for k in ('title','claim','demonstration','publisher'))
    drafts.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    reviews[row['topic_id']]={k:row[k] for k in ('title','claim','demonstration','footage','novelty','scope')}
    reviews[row['topic_id']].update(
        observation=row['title'].removeprefix('Why '),
        region='Canada example' if category=='shopping' else 'Global where the specified design is used',
        evidence_status='reviewed',
        sources=[{k:row[k] for k in ('url','publisher','passage')}|{'retrieved_at':doc['retrieved_at']}],
        editorial_scores=dict(recognition=3,overlooked_detail=4,payoff=4,evidence=3,visuals=3),
        support_review=dict(method='Primary-text comparison and channel-history replacement',reviewed_at=now().isoformat(),finding=row['claim'],scope=row['scope']),
        editorial_note=row['reason'])
path.write_text(json.dumps(reviews,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Replaced three historical overlaps; reviewed records:',len(reviews))
