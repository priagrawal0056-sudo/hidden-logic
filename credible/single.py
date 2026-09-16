"""One command from sourced Gemini draft to an unpublished measured Short."""
import argparse
from pathlib import Path
from config_loader import load_config
from .core import read,save,now
from .evidence import FreeModel,generate_episode
from .pipeline import settings,documents,prepare
from .quality import script_checks


def build(pillar, root):
    root=Path(root)
    config=settings()
    config['clip_history_path']=str(root/'preview-state'/'used_clips.json')
    cfg=load_config()
    model=FreeModel(config)
    # The same environment overlay as narration; no credentials copied into output.
    model.key=cfg.get('gemini_api_key','')
    if not model.key: raise RuntimeError('Gemini credential unavailable; set HL_GEMINI_API_KEY')
    if not (cfg.get('pexels_api_key') or cfg.get('pixabay_api_key')):
        raise RuntimeError('Stock credential unavailable; set HL_PEXELS_API_KEY or HL_PIXABAY_API_KEY')
    catalog=[s for s in read('credible/catalog.json',[]) if s['pillar']==pillar]
    docs,source_errors=documents(root,catalog)
    history=read('channel_index.json',[])+read('outputs/credible/reserve.json',[])
    # One candidate with the existing bounded automatic structural repair and
    # independent evidence review. Failure is visible; this command never uploads.
    episode=generate_episode(model,docs,history,'question_first')
    script_checks(episode)
    episode=prepare(episode,root,config)
    save(root/'result.json',{'status':'ready_for_review','at':now().isoformat(),
                           'episode':episode,'source_errors':source_errors,'published':False})
    print('Ready:',str(root/'episodes'/episode['id']/'short.mp4'),flush=True)
    return episode


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pillar',choices=('technology','travel','shopping'),default='shopping')
    parser.add_argument('--output',type=Path,default=Path('outputs/single-preview'))
    args=parser.parse_args()
    try: build(args.pillar,args.output)
    except Exception as exc:
        # Some libraries include request URLs or credentials in exception text.
        message=str(exc)
        reason=(message if message.startswith(('Gemini credential unavailable;',
            'Stock credential unavailable;','Free model request failed: HTTP')) else type(exc).__name__)
        save(args.output/'result.json',{'status':'failed','error_type':type(exc).__name__,
                                      'reason':reason,'published':False})
        raise SystemExit('Generation/render failed: '+reason+'. No upload was attempted.') from None


if __name__=='__main__': main()
