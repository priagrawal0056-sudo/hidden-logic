"""Build unpublished pilots and a local review page. Never authenticates to YouTube."""
import argparse
import html
from pathlib import Path
from .core import digest, now, read, save
from .pipeline import prepare, settings
from .evidence import verify_support
from .seeds import RECIPES, build_recipe


def production_fingerprint(config):
    files = ['media.py','storyboard.py','authored_boards.py','authored_evidence.py','seeds.py','evidence.py','quality.py']
    return digest([config, [(f,(Path(__file__).parent/f).read_text(encoding='utf-8')) for f in files]])


def require_pilot_review(config, path='state/credible/pilot_review.json'):
    review = read(path, {})
    # rollout_enabled is only the second switch: a stale or missing review is
    # never equivalent to approving the current production design.
    reviewed_config = {**config, 'rollout_enabled': False}
    if review.get('production_fingerprint') != production_fingerprint(reviewed_config):
        raise ValueError('Current production design has no matching pilot review')
    rows = review.get('pilots', [])
    if len({r.get('id') for r in rows}) < 6 or not review.get('reviewer') or not review.get('reviewed_at'):
        raise ValueError('Six distinct reviewed pilots and reviewer required')
    for pillar in ('technology','travel','shopping'):
        if sum(r.get('pillar')==pillar and r.get('approved') is True
               and len(r.get('video_sha256',''))==64 for r in rows) < 2:
            raise ValueError('Two approved finished pilots per pillar required')
    return True


def build(root, source_root):
    config = settings()
    docs = {d['url']:d for p in (source_root/'evidence').glob('*.json') if (d:=read(p))}
    docs.update({d['url']:d for d in read('credible/source_snapshots.json', [])})
    sources = {s['id']:s for s in read('credible/catalog.json')}
    episodes, errors = [], []
    for recipe in RECIPES:
        try:
            source=sources[recipe[0]]; doc=docs[source['url']]
            save(root/'evidence'/(digest(source['url'])[:20]+'.json'),doc)
            episode=build_recipe(recipe, source, doc)
            verify_support(episode['evidence'], docs)
            print('Preparing:',recipe[0],flush=True)
            episode=prepare(episode,root,config)
            episodes.append(episode)
            print('Ready:',recipe[0],episode['duration'],'answer ends',episode['scenes'][1]['narration_end'],flush=True)
        except Exception as exc:
            errors.append({'topic':recipe[0], 'error':str(exc)[:200]})
            print('Pilot rejected:',recipe[0],str(exc)[:200],flush=True)
    save(root/'reserve.json',episodes)
    save(root/'run-report.json',{'at':now().isoformat(),'reserve_ready':len(episodes),'errors':errors})
    review={'production_fingerprint':production_fingerprint(config),'reviewer':None,'reviewed_at':None,
            'pilots':[{'id':ep['id'],'pillar':ep['pillar'],'title':ep['title'],
                       'video_sha256':ep['quality']['video_sha256'],'approved':False} for ep in episodes]}
    save(root/'pilot-review-template.json',review)
    cards=[]
    for ep in episodes:
        folder='episodes/'+ep['id']
        cards.append(f'''<article><small>{html.escape(ep['pillar'])} · {ep['duration']:.1f}s ·
          first answer ends {ep['scenes'][1]['narration_end']:.2f}s</small>
          <h2>{html.escape(ep['title'])}</h2><video controls preload="metadata" src="{folder}/short.mp4"></video>
          <p>{html.escape(' '.join(ep['beats']))}</p>
          <a href="{folder}/episode.json">Evidence and checks</a></article>''')
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Hidden Logic — pilot review</title>
    <meta name="viewport" content="width=device-width, initial-scale=1"><style>
    body{margin:0;background:#10241e;color:#eef2e9;font:17px/1.5 system-ui;padding:4vw}
    header{max-width:880px;margin:0 auto 48px}h1{font-size:44px;line-height:1.1}small,a{color:#8ce0ba}
    main{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:28px}
    article{background:#193129;padding:22px;border-radius:16px}h2{font-size:23px;min-height:3em}
    video{width:100%;max-height:650px;background:#000}p{color:#c2cfc6}</style>
    <header><small>HIDDEN LOGIC / UNPUBLISHED PILOTS</small><h1>Watch the explanation.</h1>
    <p>Review at least two videos per pillar with sound. Does the opening make sense immediately?
    Is the answer useful by six seconds? Does the drawing explain it? Does the voice sound natural?
    Do captions read in phrases? Does the ending pay off the opening? Compare consecutive videos
    for visual sameness. Mark any awkward sentence, incorrect diagram or distracting cut.</p>
    <p>Automated checks do not approve artistic quality. Publishing is still disabled.
    The review template starts with every approval set to false.</p></header><main>'''+''.join(cards)+'</main></html>'
    (root/'review.html').write_text(page,encoding='utf-8')
    if errors: raise SystemExit(f'{len(errors)} pilots need revision; see {root}/run-report.json')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path('outputs/pilots-v3'))
    parser.add_argument('--source-root',type=Path,default=Path('outputs/credible'))
    args=parser.parse_args();build(args.output,args.source_root)
