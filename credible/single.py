"""One command from sourced Gemini draft to an unpublished measured Short."""
import service_limits
import argparse
from pathlib import Path
from config_loader import load_config
from footage_review import RejectedFootage
from .core import read,save,now,digest,file_hash
from .evidence import EditorialRejected,FreeModel,generate_episode
from .pipeline import settings,documents,prepare
from .topics import CATEGORY_COUNTS, load_bank, shortlist, sources_for
from .quality import script_checks
from .rejections import CandidateRejected


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
    # A category preview can choose an alternative reviewed subject after a
    # negative editorial verdict. An explicit topic request must never drift.
    choices=shortlist(bank,history,state.get('topics',{}),n=1 if topic_id else 3,
                      category=None if topic_id else category)
    if not choices: raise RuntimeError('No eligible source-reviewed topic in requested category')
    # Reuse a reviewed draft after quota/stock failure, but never across changes
    # to the authoring contract or topic. Revalidate its saved evidence locally.
    def contract_for(topic):
        return digest([topic,config['production_version'],
        file_hash(Path(__file__).with_name('evidence.py')),
        file_hash(Path(__file__).with_name('draft_schema.py')),
        file_hash(Path(__file__).parents[1]/'production_brief.py')])
    checkpoint=read(root/'draft.json',{})
    choices.sort(key=lambda topic: contract_for(topic)!=checkpoint.get('contract'))
    attempts=[]
    for topic in choices:
        contract=contract_for(topic)
        docs,source_errors=documents(root,sources_for(topic))
        episode=checkpoint.get('episode') if checkpoint.get('contract')==contract else None
        attempt={'topic_id':topic['topic_id'],'status':'reviewing','source_errors':source_errors}
        attempts.append(attempt)
        save(root/'attempts.json',attempts)
        if episode:
            from .evidence import verify_support
            verify_support(episode.get('evidence'),docs)
        else:
            try:
                episode=generate_episode(model,docs,history,'question_first',topic=topic)
            except CandidateRejected:
                attempt['status']='editorial_rejected'
                save(root/'attempts.json',attempts)
                if topic_id or topic is choices[-1]:
                    raise
                # Service errors are deliberately not caught: they retain work
                # and stop API consumption instead of cycling through subjects.
                print('Draft rejected; trying another eligible subject in this category.',flush=True)
                continue
            save(root/'draft.json',{'contract':contract,'episode':episode})
        attempt['status']='draft_reviewed'
        save(root/'attempts.json',attempts)
        script_checks(episode)
        try:
            episode=prepare(episode,root,config)
        except RejectedFootage:
            # Every selected replacement was actually assessed and rejected.
            # Keep its narration/diagnostics, but try a filmable alternative.
            # Quota, networking and malformed assessments never enter this path.
            attempt['status']='footage_rejected'
            save(root/'attempts.json',attempts)
            if topic_id or topic is choices[-1]:
                raise
            print('Footage alternatives rejected; trying another eligible subject in this category.',flush=True)
            continue
        attempt['status']='ready_for_review'
        save(root/'attempts.json',attempts)
        break
    save(root/'result.json',{'status':'ready_for_review','at':now().isoformat(),
                           'episode':episode,'source_errors':source_errors,
                           'attempts':attempts,'published':False})
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
        quota=service_limits.quota_deferral(exc)
        if quota:
            message=service_limits.quota_message(quota)
            save(args.output/'result.json',{'status':'deferred_quota','quota':quota,
                                          'reason':message,'published':False})
            print(message)
            print('Run deferred. Saved work retained for a later run. Exiting successfully.')
            return
        # Some libraries include request URLs or credentials in exception text.
        message=str(exc)
        reason=(message if isinstance(exc, (CandidateRejected, service_limits.ServiceUnavailable)) or message.startswith(('Gemini credential unavailable;',
            'Stock credential unavailable;','Free model request failed: HTTP',
            'Every stock scene needs','Footage failed sampled-frame',
            'Independent editorial review rejected','Candidate failed source/drawing validation:',
            'First useful answer must','Narration transcript','Caption overflow')) else type(exc).__name__)
        save(args.output/'result.json',{'status':'failed','error_type':type(exc).__name__,
                                      'reason':reason,'published':False})
        raise SystemExit('Generation/render failed: '+reason+'. No upload was attempted.') from None


if __name__=='__main__': main()
