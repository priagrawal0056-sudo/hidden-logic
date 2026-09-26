"""Reviewed topic briefs, transparent ranking and recoverable reservations.

The editorial bank is immutable at runtime. Production owns the lifecycle ledger;
previews must pass an isolated ledger. A selected title is never a published topic.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from pathlib import Path

from .core import now, parse, read

BANK = Path(__file__).with_name('topics.json')
CATEGORY_COUNTS = {'home': 80, 'buildings': 80, 'technology': 70, 'food': 65,
                   'packaging': 65, 'transport': 65, 'shopping': 40, 'clothing': 35}
DIMENSIONS = ('recognition', 'overlooked_detail', 'payoff', 'evidence', 'visuals')
LEGACY_PILLARS = {'home':'technology', 'buildings':'travel', 'technology':'technology',
                 'food':'shopping', 'packaging':'shopping', 'transport':'travel',
                 'shopping':'shopping', 'clothing':'shopping'}
ACTIVE = {'reserved', 'prepared', 'ready', 'needs_rebuild', 'allocated',
          'uploading', 'uploaded', 'scheduling', 'scheduled', 'uncertain', 'upload_uncertain'}


def load_bank(path=BANK):
    return read(path, [])


def validate_bank(bank, exact=True):
    if exact and Counter(r.get('category') for r in bank) != Counter(CATEGORY_COUNTS):
        raise ValueError('Bank must contain exactly 500 briefs with agreed category totals')
    for key in ('topic_id', 'claim_id', 'title'):
        if len({r.get(key) for r in bank}) != len(bank):
            raise ValueError('Duplicate or missing ' + key)
    required = ('topic_id', 'claim_id', 'title', 'subject', 'category', 'observation',
                'claim', 'novelty', 'scope', 'footage', 'demonstration', 'sources')
    for row in bank:
        if any(not row.get(k) for k in required):
            raise ValueError('Incomplete topic brief: ' + str(row.get('topic_id')))
        if row['category'] not in CATEGORY_COUNTS:
            raise ValueError('Unknown category')
        scores = row.get('editorial_scores', {})
        if set(scores) != set(DIMENSIONS) or any(type(v) is not int or not 0 <= v <= 4 for v in scores.values()):
            raise ValueError('Five integer editorial scores from zero to four required')
        for source in row['sources']:
            if not source.get('url', '').startswith('https://') or not source.get('publisher'):
                raise ValueError('Reviewed HTTPS primary source required')
        if row.get('evidence_status') == 'reviewed':
            if not row.get('support_review') or not all(s.get('passage') and s.get('retrieved_at') for s in row['sources']):
                raise ValueError('Reviewed briefs require retrieved support and semantic review')
    return True


def evidence_ready(topic):
    return (topic.get('evidence_status') == 'reviewed' and bool(topic.get('support_review'))
            and all(s.get('passage') and s.get('retrieved_at') for s in topic.get('sources', []))
            and bool(topic.get('sources')))


def editorial_hold(topic):
    # A pending evidence score of zero means research is needed, not a veto.
    return bool(topic.get('editorial_hold')) or any(
        topic.get('editorial_scores', {}).get(k, 0) < 2
        for k in DIMENSIONS if k != 'evidence')


def score(topic):
    """Equal weight, 0–100. Editorial judgment, never a predicted view count."""
    values = [topic.get('editorial_scores', {}).get(k, 0) for k in DIMENSIONS]
    return sum(values) * 5 if not editorial_hold(topic) and all(v >= 2 for v in values) else 0


def eligible(topic, history, ledger, at=None):
    from .core import duplicate
    at = at or now()
    if not evidence_ready(topic) or not score(topic):
        return False
    record = ledger.get(topic['topic_id'], {})
    status = record.get('status')
    if status in ACTIVE:
        # Only a pre-render reservation may expire. An uncertain upload never may.
        if status != 'reserved' or not record.get('expires_at') or parse(record['expires_at']) > at:
            return False
    if status in ('published', 'rejected'):
        return False
    if record.get('retry_after') and parse(record['retry_after']) > at:
        return False
    for other_id, other in ledger.items():
        if other_id == topic['topic_id'] or other.get('status') not in ACTIVE:
            continue
        if other.get('status') == 'reserved' and other.get('expires_at') and parse(other['expires_at']) <= at:
            continue
        if other.get('status') == 'scheduled' and other.get('publish_at') and parse(other['publish_at']) <= at:
            continue  # Published history applies the dated 14/90-day windows.
        if other.get('claim_id') == topic['claim_id'] or (other.get('subject') and other['subject'] == topic['subject']):
            return False
    return duplicate(topic, history, at=at) is None


def shortlist(bank, history=(), ledger=None, n=6, category=None, at=None):
    at, ledger = at or now(), ledger or {}
    pool = [r for r in bank if (category is None or r['category'] == category)
            and eligible(r, history, ledger, at)]
    counts = Counter()
    for row in history:
        date = row.get('publish_at') or row.get('reserved_at') or row.get('date')
        try:
            recent = not date or (at - parse(date if 'T' in date else date + 'T00:00:00+00:00')).days < 28
        except (ValueError, TypeError):
            recent = True
        if recent:
            counts[row.get('category') or row.get('pillar')] += 1
    chosen, subjects, categories = [], set(), Counter()
    while pool and len(chosen) < max(0, n):
        # Cover different categories before repeating any; then reduce recent skew.
        pool.sort(key=lambda r: (categories[r['category']], counts[r['category']],
                                 -score(r), r['topic_id']))
        row = pool.pop(0)
        if row['subject'] in subjects:
            continue
        chosen.append(row); subjects.add(row['subject']); categories[row['category']] += 1
    return chosen


def reserve_topic(ledger, topic, owner, at=None):
    at = at or now()
    previous = ledger.get(topic['topic_id'], {})
    if previous.get('status') in ACTIVE:
        if previous.get('status') != 'reserved' or not previous.get('expires_at') or parse(previous['expires_at']) > at:
            raise ValueError('Topic already reserved')
    ledger[topic['topic_id']] = {'status': 'reserved', 'owner': owner,
        'claim_id': topic['claim_id'], 'subject':topic['subject'], 'category':topic['category'], 'reserved_at': at.isoformat(),
        'expires_at': (at + dt.timedelta(hours=6)).isoformat()}


def balanced_slot(category, slot_indices, history=(), candidates=()):
    """Cover open slots, then prefer times least used by this category.

    Draft candidates count only toward this run's coverage. Historical counts
    come from assigned episodes, never the position of a topic in a shortlist.
    Opening-format balancing is still handled separately by core.assignment.
    """
    indices = sorted(set(slot_indices))
    if not indices:
        raise ValueError('No open slots to assign')
    pending, category_counts, total = Counter(), Counter(), Counter()
    for row in candidates:
        index = row.get('experiment', {}).get('slot_index')
        if index in indices:
            pending[index] += 1
    for row in history:
        index = row.get('slot_index', row.get('experiment', {}).get('slot_index'))
        if index not in indices:
            continue
        total[index] += 1
        if row.get('category') == category:
            category_counts[index] += 1
    return min(indices, key=lambda i: (pending[i], category_counts[i], total[i], i))


def release_topic(ledger, topic_id, reason, at=None):
    record = ledger.get(topic_id, {})
    if record.get('status') != 'reserved':
        return  # Prepared or potentially uploaded work must be recovered, not freed.
    # A fully rejected set of stock alternatives will not become filmable six
    # hours later. Give other reviewed subjects a turn without consuming this one.
    delay = dt.timedelta(days=7) if reason == 'RejectedFootage' else dt.timedelta(hours=6)
    record.update(status='available', last_failure=reason,
                  retry_after=((at or now()) + delay).isoformat())


def sync_ledger(ledger, episodes):
    for episode in episodes:
        topic_id = episode.get('topic_id')
        if topic_id:
            ledger.setdefault(topic_id, {}).update(status=episode.get('status', 'prepared'),
                claim_id=episode.get('claim_id'), subject=episode.get('subject'), category=episode.get('category'),
                episode_id=episode.get('episode_id', episode.get('id')),
                publish_at=episode.get('publish_at'), video_id=episode.get('video_id'))


def sources_for(topic):
    return [{'id': topic['topic_id'] + '-' + str(i), **source}
            for i, source in enumerate(topic['sources'])]


def verified_documents(topic, documents):
    """Fail closed when stored support no longer appears in the current source."""
    from .evidence import verify_support
    if not evidence_ready(topic):
        raise ValueError('Topic has not passed source support review')
    verify_support([{'source_url': s['url'], 'passage': s['passage'],
                     'claim': topic['claim'], 'scope': topic['scope']} for s in topic['sources']], documents)
    return documents
