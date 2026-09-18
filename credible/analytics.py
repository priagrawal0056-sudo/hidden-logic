"""Timestamped observations and matched-age experiments; missing is never zero."""
from __future__ import annotations

import datetime as dt
import statistics
from pathlib import Path

from .core import UTC, now, parse, read, save

METRICS = ('engagedViews', 'averageViewDuration', 'averageViewPercentage',
           'shares', 'subscribersGained', 'subscribersLost')


def error_detail(exc):
    import json
    try:
        error = json.loads(exc.content).get('error', {})
        reason = ','.join(e.get('reason','') for e in error.get('errors',[]))
        return {'type':type(exc).__name__, 'status':error.get('code'),
                'reason':reason, 'message':error.get('message','')[:400]}
    except (AttributeError,ValueError,TypeError):
        return {'type':type(exc).__name__}


def migrate_legacy(data):
    result = {}
    for vid, record in data.items():
        result[vid] = {'video_id': vid, 'title': record.get('title'),
                       'legacy': record, 'experiment_eligible': False,
                       'reason': 'Legacy metric definitions and observation ages not verified'}
    return result


def observation(video_id, stats, at, publish_at):
    return {'video_id': video_id, 'observed_at': at.isoformat(),
            'age_hours': round((at - parse(publish_at)).total_seconds() / 3600, 3),
            'public_views': int(stats['viewCount']) if 'viewCount' in stats else None,
            'likes': int(stats['likeCount']) if 'likeCount' in stats else None,
            'comments': int(stats['commentCount']) if 'commentCount' in stats else None}


def query_metrics(api, video_id, start, end):
    values, errors = {}, {}
    # Isolate metric compatibility failures. A missing engagement report must not
    # erase a valid watch-time result or silently turn it into zero.
    for group in (METRICS[:3], METRICS[3:]):
        try:
            report = api.reports().query(ids='channel==MINE', startDate=start,
                endDate=end, dimensions='video', filters='video==' + video_id,
                metrics=','.join(group), maxResults=1).execute()
            columns = [c['name'] for c in report.get('columnHeaders', [])]
            rows = report.get('rows', [])
            row = dict(zip(columns, rows[0])) if rows else {}
            for key in group:
                values[key] = row.get(key)
                if key not in row:
                    errors[key] = 'No report row yet'
        except Exception as exc:
            for key in group:
                values[key] = None
                errors[key] = error_detail(exc)
    return {'metrics': values, 'availability': errors}


def retention_drops(curve, scenes, duration):
    result = []
    for previous, current in zip(curve, curve[1:]):
        seconds = current[0] * duration
        delta = previous[1] - current[1]
        if delta >= .08:
            scene = next((i for i, s in enumerate(scenes)
                          if s['start'] <= seconds < s['end']), None)
            result.append({'seconds': round(seconds, 2), 'watch_ratio_drop': round(delta, 4),
                           'scene': scene})
    return result


def poll(state_dir='state/credible', at=None, services=None):
    at = at or now()
    root = Path(state_dir)
    production = read(root / 'production.json', {'slots': {}})
    data = read(root / 'analytics.json', {'schema_version': 2, 'videos': {}})
    if not (root / 'legacy_analytics.json').exists():
        save(root / 'legacy_analytics.json', migrate_legacy(read('ab_log.json', {})))
    if services is None:
        import upload
        yt, api = upload._service(), upload._analytics()
    else:
        yt, api = services
    import re
    tracked = list(production['slots'].values())
    known = {r.get('video_id') for r in tracked}
    for vid, legacy in read('ab_log.json', {}).items():
        if vid in known or not legacy.get('publish_at'):
            continue
        try:
            age = (at-parse(legacy['publish_at'])).days
        except (ValueError,TypeError):
            continue
        if 0 <= age <= 35:
            tracked.append({'video_id':vid,'publish_at':legacy['publish_at'], 'title':legacy.get('title',''),
                            'experiment':{'id':'legacy-baseline','arm':'baseline'},'pillar':legacy.get('cluster')})
    for slot in tracked:
        vid = slot.get('video_id')
        if not vid or parse(slot['publish_at']) >= at:
            continue
        record = data['videos'].setdefault(vid, {'observations': []})
        record.update({k: slot[k] for k in ('publish_at', 'pillar', 'category', 'topic_id', 'experiment', 'title') if k in slot})
        try:
            response = yt.videos().list(part='statistics', id=vid).execute()
            stats = response.get('items', [{}])[0].get('statistics', {})
            record['observations'].append(observation(vid, stats, at, slot['publish_at']))
            record['observations'] = record['observations'][-120:]
        except Exception as exc:
            record['statistics_error'] = type(exc).__name__
        published = parse(slot['publish_at'])
        if (at-published).days > 35 and record.get('seven_day'):
            continue
        # Analytics API dates are Pacific dates, not upload-relative 24h windows.
        # Use seven COMPLETE Pacific calendar days after the publication day.
        from zoneinfo import ZoneInfo
        day = published.astimezone(ZoneInfo('America/Los_Angeles')).date()
        start, end = day + dt.timedelta(days=1), day + dt.timedelta(days=7)
        ready = at.astimezone(ZoneInfo('America/Los_Angeles')).date() >= end + dt.timedelta(days=3)
        fetched = record.get('seven_day', {}).get('fetched_at')
        refresh = not fetched or (at-parse(fetched)).total_seconds() >= 23*3600
        if ready and refresh:
            report = query_metrics(api, vid, start.isoformat(), end.isoformat())
            record['seven_day'] = {**report, 'start_date': start.isoformat(),
                'end_date': end.isoformat(), 'window': 'seven_complete_pacific_days_after_publish_day',
                'fetched_at': at.isoformat()}
            try:
                curve_report = api.reports().query(ids='channel==MINE',
                    startDate=start.isoformat(), endDate=end.isoformat(),
                    filters='video==' + vid, dimensions='elapsedVideoTimeRatio',
                    metrics='audienceWatchRatio', sort='elapsedVideoTimeRatio').execute()
                curve = curve_report.get('rows', [])
                record['retention_curve'] = curve
                record['retention_availability'] = 'available' if curve else 'unavailable'
                record['scene_drops'] = retention_drops(curve, slot.get('scenes', []), slot.get('duration', 1))
            except Exception as exc:
                record['retention_availability'] = type(exc).__name__
        record['stayed_to_watch'] = record.get('stayed_to_watch')  # Studio-only optional import
        record['experiment_eligible'] = bool(ready and record.get('experiment',{}).get('id') in ('early-answer-v1','everyday-topics-v2')
                                             and record.get('seven_day', {}).get('metrics', {}).get('engagedViews'))
    data['last_polled_at'] = at.isoformat()
    save(root / 'analytics.json', data)
    report = experiment_report(data, 'everyday-topics-v2')
    report['previous_experiment'] = experiment_report(data, 'early-answer-v1')
    save(root / 'experiment_report.json', report)
    return report


def experiment_report(data, experiment_id='early-answer-v1'):
    groups = {arm: [] for arm in ('demonstration_first', 'question_first')}
    for record in data.get('videos', {}).values():
        arm = record.get('experiment', {}).get('arm')
        metrics = record.get('seven_day', {}).get('metrics', {})
        if (arm in groups and record.get('experiment_eligible')
                and record.get('experiment', {}).get('id') == experiment_id
                and all(metrics.get(k) is not None for k in METRICS)
                and metrics['engagedViews'] >= 100):
            groups[arm].append(record)
    summary = {}
    for arm, records in groups.items():
        rows = [r['seven_day']['metrics'] for r in records]
        med = lambda k: statistics.median(r[k] for r in rows) if rows else None
        summary[arm] = {'eligible_videos': len(rows), 'median_apv': med('averageViewPercentage'),
            'median_avd_seconds': med('averageViewDuration'), 'median_engaged_views': med('engagedViews'),
            'shares_per_1000_engaged': statistics.median(r['shares'] / r['engagedViews'] * 1000 for r in rows) if rows else None,
            'net_subscribers_per_1000_engaged': statistics.median((r['subscribersGained'] - r['subscribersLost']) / r['engagedViews'] * 1000 for r in rows) if rows else None}
    ready = all(len(rows) >= 20 for rows in groups.values())
    return {'experiment_id': experiment_id, 'arms': summary, 'decision': 'review_guardrails' if ready else 'continue_balanced_testing',
        'automatic_promotion': False, 'minimum_per_arm': 20, 'minimum_engaged_views_per_video': 100,
        'note': 'APV target is +10 percentage points against a comparable baseline, not a promise. '
                'Review pillar/slot balance, duration, reach and engagement before choosing.'}


if __name__ == '__main__':
    print(poll())
