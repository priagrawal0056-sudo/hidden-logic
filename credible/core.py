from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
PILLARS = ('technology', 'travel', 'shopping')
FORMATS = ('demonstration', 'comparison', 'process')


def now():
    return dt.datetime.now(UTC)


def parse(value):
    value = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    return value.astimezone(UTC)


def read(path, default=None):
    p = Path(path)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def tokens(value):
    return re.findall(r'[a-z0-9]+', value.lower())


def claim_key(value):
    aliases = {'cars': 'car', 'automobile': 'car', 'automobiles': 'car',
               'speeding': 'speed', 'faster': 'speed', 'fast': 'speed',
               'queues': 'queue', 'lines': 'queue', 'line': 'queue',
               'prices': 'price', 'batteries': 'battery'}
    stop = set('why how the a an you your always does do is are look looks seem seems'.split())
    return set(aliases.get(t, t) for t in tokens(value) if t not in stop)


def duplicate(candidate, history, at=None):
    at = at or now()
    for old in history:
        # Unused reserve items are reserved regardless of their creation age.
        date = old.get('publish_at') or old.get('reserved_at') or old.get('date')
        if date:
            try:
                age = (at - parse(date if 'T' in date else date + 'T00:00:00+00:00')).days
            except ValueError:
                age = 0  # Unknown history cannot silently permit duplicates.
        else:
            age = 0
        if old.get('status') in ('ready', 'needs_rebuild'):
            age = 0
        if age >= 90:
            continue
        if candidate.get('claim_id') and candidate.get('claim_id') == old.get('claim_id'):
            return 'same claim within 90 days'
        a = claim_key(candidate.get('claim', '') or candidate.get('title', ''))
        b = claim_key(old.get('claim', '') or old.get('title', ''))
        if a and b and len(a & b) / min(len(a), len(b)) >= .8:
            return 'similar underlying claim'
        if age < 14 and candidate.get('subject') and candidate['subject'] == old.get('subject'):
            return 'subject within 14 days'
    return None


def slots(config, at=None, days=2):
    at = at or now()
    zone = ZoneInfo(config['timezone'])
    local = at.astimezone(zone)
    result = []
    for offset in range(days + 1):
        day = local.date() + dt.timedelta(days=offset)
        for index, clock in enumerate(config['publish_slots']):
            hour, minute = map(int, clock.split(':'))
            value = dt.datetime.combine(day, dt.time(hour, minute), zone).astimezone(UTC)
            if value > at + dt.timedelta(minutes=config.get('upload_lead_minutes', 120)):
                result.append({'id': value.strftime('%Y%m%dT%H%MZ'),
                               'publish_at': value.isoformat(), 'slot_index': index})
    return result[:config['videos_per_day']]


def assignment(pillar, slot_index, history):
    counts = {v: 0 for v in ('demonstration_first', 'question_first')}
    for row in history:
        ex = row.get('experiment', {})
        if row.get('pillar') == pillar and ex.get('slot_index') == slot_index:
            arm = ex.get('arm')
            if arm in counts:
                counts[arm] += 1
    arm = min(counts, key=lambda a: (counts[a], a))
    return {'id': 'early-answer-v1', 'arm': arm, 'slot_index': slot_index,
            'assigned_at': now().isoformat(), 'promote_automatically': False}


@contextlib.contextmanager
def lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)
