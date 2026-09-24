"""One command from sourced Gemini draft to an unpublished measured Short."""
import service_limits
import argparse
from pathlib import Path
from config_loader import load_config
from .core import read,save,now,digest,file_hash
from .evidence import FreeModel,generate_episode
from .pipeline import settings,documents,prepare
from .topics import CATEGORY_COUNTS, load_bank, shortlist, sources_for
from .quality import script_checks


@service_limits.session()
def build(pillar, root, topic_id=None):
    root=Path(root)
    config=settings()
    config['clip_history_path']=str(root/'preview-state'/'used_clips.json')
    cfg=load_config()
    model=FreeModel(config)
    model.diagnostics_dir=root/'diagnostics'
    # The same environment overlay as narration; no credentials copied into output.
    model.key=cfg.get('gemini_api_key','')
    if not model.key: raise RuntimeError('Gemini credential unavailable; set HL_GEMINI_API_KEY')
    if not (cfg.get('pexels_api_key') or cfg.get('pixabay_api_key')):
        raise RuntimeError('Stock credential unavailable; set HL_PEXELS_API_KEY or HL_PIXABAY_API_KEY')
    state=read('state/credible/production.json', {'slots':{}})
    from .pipeline import history as production_history
    history=production_history(state,read('outputs/credible/reserve.json',[]))
    from .topic_review import reviewed_bank
    bank=reviewed_bank(load_bank(),state.get('topic_reviews',{}))
    if topic_id:
        bank=[t for t in bank if t['topic_id']==topic_id]
    category={'travel':'transport'}.get(pillar,pillar)
    choices=shortlist(bank,history,state.get('topics',{}),n=1,category=None if topic_id else category)
    if not choices: raise RuntimeError('No eligible source-reviewed topic in requested category')
    topic=choices[0]
    docs,source_errors=documents(root,sources_for(topic))
    # One candidate with the existing bounded automatic structural repair and
    # independent evidence review. Failure is visible; this command never uploads.
    # Reuse a reviewed draft after quota/stock failure, but never across changes
    # to the authoring contract or topic. Revalidate its saved evidence locally.
    contract=digest([topic,config['production_version'],
        file_hash(Path(__file__).with_name('evidence.py')),
        file_hash(Path(__file__).with_name('draft_schema.py')),
        file_hash(Path(__file__).parents[1]/'production_brief.py')])
    checkpoint=read(root/'draft.json',{})
    episode=checkpoint.get('episode') if checkpoint.get('contract')==contract else None
    if episode:
        from .evidence import verify_support
        verify_support(episode.get('evidence'),docs)
    else:
        episode=generate_episode(model,docs,history,'question_first',topic=topic)
        save(root/'draft.json',{'contract':contract,'episode':episode})
    script_checks(episode)
    episode=prepare(episode,root,config)
    save(root/'result.json',{'status':'ready_for_review','at':now().isoformat(),
                           'episode':episode,'source_errors':source_errors,'published':False})
    print('Ready:',str(root/'episodes'/episode['id']/'short.mp4'),flush=True)
    return episode


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--category',choices=tuple(CATEGORY_COUNTS))
    parser.add_argument('--pillar',choices=('technology','travel','shopping'),default='shopping',help='Legacy category alias')
    parser.add_argument('--topic-id',help='Preview a specific eligible brief')
    parser.add_argument('--output',type=Path,default=Path('outputs/single-preview'))
    args=parser.parse_args()
    try: build(args.category or args.pillar,args.output,args.topic_id)
    except Exception as exc:
        # Some libraries include request URLs or credentials in exception text.
        message=str(exc)
        reason=(message if isinstance(exc, service_limits.ServiceUnavailable) or message.startswith(('Gemini credential unavailable;',
            'Stock credential unavailable;','Free model request failed: HTTP',
            'Every stock scene needs','Footage failed sampled-frame',
            'Independent editorial review rejected','Candidate failed source/drawing validation:',
            'First useful answer must','Narration transcript','Caption overflow')) else type(exc).__name__)
        save(args.output/'result.json',{'status':'failed','error_type':type(exc).__name__,
                                      'reason':reason,'published':False})
        raise SystemExit('Generation/render failed: '+reason+'. No upload was attempted.') from None


if __name__=='__main__': main()
