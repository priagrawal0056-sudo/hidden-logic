"""Keep the old script API while using the shared sourced writer for bank topics."""
from pathlib import Path
from .core import read
from .topics import load_bank, shortlist, sources_for


def generate(api_key, title=None):
    from .pipeline import settings, documents
    from .evidence import FreeModel, generate_episode
    from .approved import metadata
    from idea_bank import history
    rows, ledger = history()
    from .topic_review import reviewed_bank
    state = read('state/credible/production.json', {})
    bank = reviewed_bank(load_bank(), state.get('topic_reviews', {}))
    if title:
        bank = [r for r in bank if title in (r['title'], r['topic_id'])]
        if not bank:
            raise ValueError('Topic must match a reviewed bank title or topic_id; add and source a brief first')
    selected = shortlist(bank, rows, ledger, n=1)
    if not selected:
        raise ValueError('No eligible source-reviewed topic; no unsourced fallback')
    topic = selected[0]
    docs, _ = documents(Path('outputs/legacy-evidence'), sources_for(topic))
    model = FreeModel(settings()); model.key = api_key
    episode = generate_episode(model, docs, rows, 'question_first', topic=topic)
    return {**metadata(episode), **{k:episode[k] for k in ('topic_id','category','pillar','claim_id','subject')},
            'topic': topic['title'], 'factcheck': 'source_checked',
            'production_version': settings()['production_version']}
