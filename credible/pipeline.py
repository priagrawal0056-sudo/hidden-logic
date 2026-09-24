from __future__ import annotations
import service_limits

import argparse
import copy
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .core import assignment, duplicate, lock, now, parse, read, save, slots, digest, file_hash
from .evidence import FreeModel, generate_episode, retrieve, verify_support
from .media import render, synthesize
from .quality import rendered_checks, script_checks, timeline_checks, editorial_checks
from .seeds import RECIPES, build_recipe
from .topics import load_bank, shortlist, reserve_topic, release_topic, sync_ledger, sources_for, balanced_slot


class DailyIncompleteError(RuntimeError):
    """An expected incomplete run; recovery details are in run-report.json."""


def settings():
    return read('credible/settings.json')


def documents(root, catalog):
    result, errors = {}, []
    snapshots = {s['url']: s for s in read('credible/source_snapshots.json', [])}
    for source in catalog:
        try:
            result[source['url']] = retrieve(source, root / 'evidence')
        except Exception as exc:
            issue = {'source': source['id'], 'error': type(exc).__name__}
            errors.append(issue)
            if source['url'] in snapshots:
                issue.update(fallback='reviewed_snapshot',
                             retrieved_at=snapshots[source['url']].get('retrieved_at'))
                result[source['url']] = snapshots[source['url']]
                save(root/'evidence'/(digest(source['url'])[:20]+'.json'),snapshots[source['url']])
    return result, errors


def prepare(episode, root, config):
    # Never silently republish an old visual style from a warm cache.
    if episode.get('production_version') != config['production_version']:
        raise ValueError('Episode needs editorial migration before rebuilding')
    folder = root / 'episodes' / episode['id']
    folder.mkdir(parents=True, exist_ok=True)
    previous = read(folder / 'episode.json')
    from editorial_media import fingerprint
    style = fingerprint() if config['production_version'] >= 4 else []
    from config_loader import load_config
    media_config = load_config() if config['production_version']>=4 else {}
    voice_style = [[k,media_config.get(k)] for k in
                   ('tts_engine','gemini_voice','gemini_tts_model','narration_direction','allow_voice_fallback')]
    voice_style += [entry for entry in style if entry[0]=='tts.py']
    narration_signature = digest([episode['beats'],config['voice'],config.get('voice_rate'),voice_style])
    renderer_signature = digest([(name,file_hash(Path(__file__).parent/name))
                                for name in ('media.py','storyboard.py','quality.py')])
    signature = digest([narration_signature,episode['storyboard'],episode['evidence'],episode['source_label'],
                        config['width'],config['height'],config['fps'],config['production_version'],renderer_signature,
                        style, episode.get('broll_keywords'), episode.get('sound_cues'),
                        episode.get('diagram_sentence_index'),episode.get('diagram_sentence_count')])
    if previous and previous.get('quality', {}).get('passed') and previous.get('render_signature') == signature:
        try:
            previous['quality'] = rendered_checks(previous, folder, config)
            return previous
        except (ValueError, OSError):
            # A manifest can survive partial cache eviction. Rebuild the video
            # instead of permanently abandoning an otherwise verified episode.
            pass
    script_checks(episode)
    episode = copy.deepcopy(episode)
    voice_asset = next((a for a in (previous or {}).get('assets',[]) if a.get('path')=='voice.mp3'),None)
    if (previous and previous.get('narration_signature')==narration_signature and voice_asset
            and (folder/'voice.mp3').exists() and file_hash(folder/'voice.mp3')==voice_asset['sha256']
            and (config['production_version'] < 4 or
                 ((folder/'timings.json').exists() and file_hash(folder/'timings.json')==previous.get('timing_sha256')))):
        for key in ('duration','scenes','captions','voice','assets','beats_timing','first_answer_end'):
            if key in previous: episode[key]=copy.deepcopy(previous[key])
        if config['production_version'] >= 4:
            # Missing picture assets can be rebuilt without regenerating the voice.
            import captions
            from editorial_media import caption_records
            captions.build_ass(str(folder/'timings.json'),str(folder/'captions.ass'),accent='gold')
            episode['captions'] = caption_records(folder/'captions.ass')
            episode['assets'] = [voice_asset]
            episode['scenes'] = episode['beats_timing']
    else:
        episode = synthesize(episode, folder, config)
    timeline_checks(episode, folder, config)
    episode.pop('quality', None)
    episode.pop('render_signature', None)
    # Narration has already passed transcript and timing checks. Preserve that
    # expensive, measured work even if footage review or rendering fails later.
    episode['status'] = 'narration_ready'
    episode['narration_signature'] = narration_signature
    if config['production_version'] >= 4:
        episode['timing_sha256'] = file_hash(folder/'timings.json')
    save(folder / 'episode.json', episode)
    render(episode, folder, config)
    episode['quality'] = rendered_checks(episode, folder, config)
    episode['render_version'] = config['production_version']
    episode['render_signature'] = signature
    episode['narration_signature'] = narration_signature
    if config['production_version'] >= 4:
        episode['timing_sha256'] = file_hash(folder/'timings.json')
    episode['status'] = 'ready'
    save(folder / 'episode.json', episode)
    return episode


def history(state, reserve):
    legacy = read('channel_index.json', [])
    # Preview ledgers are isolated for writes, but must still observe live slots
    # and reserves. A missing media cache does not make a reserved topic unused.
    production = read('state/credible/production.json', {'slots':{}})
    slot_rows = list(state['slots'].values()) + list(production['slots'].values())
    allocated = {r.get('episode_id') for r in slot_rows if r.get('episode_id')}
    reserve_rows = [r for r in reserve + read('state/credible/reserve.json', [])
                    if r.get('status') in ('ready','needs_rebuild','reserved','allocated')
                    and r.get('id') not in allocated]
    pending_rows = list(state.get('pending_episodes', {}).values()) + list(production.get('pending_episodes', {}).values())
    all_rows = slot_rows + reserve_rows + pending_rows + legacy
    seen, result = set(), []
    for row in all_rows:
        key = row.get('video_id') or row.get('id') or digest(row)
        if key not in seen:
            seen.add(key); result.append(row)
    return result


def seed_reserve(root, config, docs, catalog, state, reserve, errors, limit=9):
    sources = {s['id']: s for s in catalog}
    attempts = 0
    for recipe in RECIPES:
        if service_limits.blocked() or attempts >= config.get('reserve_build_attempts_per_run', 3):
            break
        if len([r for r in reserve if r.get('status') == 'ready']) >= limit:
            break
        source = sources[recipe[0]]
        if source['url'] not in docs:
            continue
        try:
            episode = build_recipe(recipe, source, docs[source['url']], version=config['production_version'])
            if duplicate(episode, history(state, reserve)):
                continue
            verify_support(episode['evidence'], docs)
            attempts += 1
            episode = prepare(episode, root, config)
            reserve.append(episode)
            save(root / 'reserve.json', reserve)
            print('Prepared reserve:', episode['title'], flush=True)
        except Exception as exc:
            errors.append({'candidate': recipe[0], 'error': str(exc)[:180]})
            print('Reserve unavailable:', recipe[0], type(exc).__name__, flush=True)


@service_limits.session()
def run(mode='preview', root=Path('outputs/credible'), state_dir=Path('state/credible')):
    config = settings()
    if mode == 'publish':
        if not config['rollout_enabled']:
            raise RuntimeError('Rollout disabled until six pilot renders have passed review')
        from .pilots import require_pilot_review
        require_pilot_review(config)
    root, state_dir = Path(root), Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    # Preview state is isolated: dry runs cannot consume real slots or learning data.
    if mode != 'publish':
        state_dir = root / 'preview-state'
    config['clip_history_path'] = str(state_dir/'used_clips.json')
    with lock(state_dir / 'pipeline.lock'):
        state = read(state_dir / 'production.json', {'schema_version': 2, 'slots': {}})
        reserve = read(root / 'reserve.json', [])
        topic_ledger = state.setdefault('topics', {})
        pending = state.setdefault('pending_episodes', {})
        allocated_ids = {r.get('episode_id', r.get('id'))
                         for r in reserve + list(state['slots'].values())}
        # Recover a process stopped between saving its destination and cleanup.
        for episode_id in list(pending):
            if episode_id in allocated_ids:
                pending.pop(episode_id)
        sync_ledger(topic_ledger, reserve + list(state['slots'].values()) + list(pending.values()))
        errors = []
        # Cache eviction is recoverable: rebuild verified ready episodes from their
        # saved scripts, rather than considering a missing video a usable reserve.
        for n, episode in enumerate(reserve):
            if episode.get('status') in ('ready','needs_rebuild'):
                try:
                    reserve[n] = prepare(episode, root, config)
                except Exception as exc:
                    episode['status'] = ('needs_rebuild' if episode.get('production_version') == config['production_version']
                                         else 'superseded')
                    errors.append({'reserve': episode['id'], 'error': str(exc)[:160]})
        save(root/'reserve.json', reserve)
        catalog = read('credible/catalog.json')
        if mode != 'bootstrap' and config.get('supplementary_discovery', False):
            from .discovery import discover
            catalog += discover(catalog, root/'evidence', state_dir/'discovery.json')
        docs, source_errors = documents(root, catalog)
        errors.extend(source_errors)
        # Authored scripts need no writer calls; new Orus narration still needs TTS quota.
        if mode == 'bootstrap':
            seed_reserve(root, config, docs, catalog, state, reserve, errors, config['reserve_target'])
            save(root / 'run-report.json', {'reserve_ready': sum(r.get('status') == 'ready' for r in reserve), 'errors': errors})
            return reserve
        candidates = []
        # Finish a grounded script before spending quota on another writer call.
        # Pending drafts are part of the durable production ledger, so a quota
        # failure or interrupted worker cannot make their claims look unused.
        for episode_id, draft in list(pending.items()):
            if service_limits.blocked():
                break
            try:
                candidates.append(prepare(draft, root, config))
            except Exception as exc:
                errors.append({'resume': episode_id, 'error': str(exc)[:160]})
                if not service_limits.blocked():
                    pending.pop(episode_id)
                    release_topic(topic_ledger, draft.get('topic_id'), type(exc).__name__)
                save(state_dir/'production.json', state)
        model = FreeModel(config)
        model.diagnostics_dir = root / 'diagnostics'
        bank = load_bank()
        from .topic_review import reviewed_bank, review_topic, revision, review_queue
        baseline_reviews=read('state/credible/production.json',{}).get('topic_reviews',{})
        reviews=state.setdefault('topic_reviews',copy.deepcopy(baseline_reviews))
        attempts=state.setdefault('topic_review_attempts',{})
        effective=reviewed_bank(bank,reviews)
        # Bounded, automatic pre-script review. Failures never mark a topic used.
        review_count=0
        for lead in review_queue(effective, attempts, now().date().isoformat()):
            if review_count >= config.get('topic_reviews_per_run',6) or not model.key or model.exhausted or service_limits.blocked():
                break
            review_count+=1
            try:
                lead_docs, lead_errors=documents(root,sources_for(lead))
                errors.extend(lead_errors)
                reviews[lead['topic_id']]=review_topic(model,lead,lead_docs)
                result='reviewed'
            except Exception as exc:
                result=type(exc).__name__
                errors.append({'topic_review':lead['topic_id'],'error':result})
            attempts[lead['topic_id']]={'revision':revision(lead),'date':now().date().isoformat(),'result':result}
            save(state_dir/'production.json',state)
        bank=reviewed_bank(bank,reviews)
        run_day = now().astimezone(ZoneInfo(config['timezone'])).date().isoformat()
        plan_slots = state.setdefault('run_days', {}).get(run_day)
        if plan_slots is None:
            plan_slots = slots(config)
            state['run_days'][run_day] = plan_slots
            save(state_dir/'production.json', state)
        visible_ledger = topic_ledger
        if mode != 'publish':
            visible_ledger = {**read('state/credible/production.json',{}).get('topics',{}), **topic_ledger}
        open_indices = [s['slot_index'] for s in plan_slots if s['id'] not in state['slots']]
        # If today's slots already exist, fresh candidates can replenish reserves.
        candidate_indices = open_indices or [s['slot_index'] for s in plan_slots]
        # Six briefs are alternatives, not six compulsory renders. Finish the
        # open slots first; completed-day reruns replenish one reserve at a time.
        candidate_target = len(open_indices) or int(
            sum(r.get('status') == 'ready' for r in reserve) < config['reserve_target'])
        want_topics = not service_limits.blocked() and len(candidates) < candidate_target
        topics = (shortlist(bank, history(state, reserve), visible_ledger, config['briefs_per_day'])
                  if want_topics else [])
        if want_topics and not topics:
            errors.append({'topics': 'No eligible source-reviewed briefs; use verified reserve only'})
        for i, topic in enumerate(topics):
            if len(candidates) >= candidate_target:
                break
            reserve_topic(topic_ledger, topic, run_day)
            save(state_dir/'production.json', state)
            assigned_history = list(state['slots'].values())
            preferred_slot = balanced_slot(topic['category'], candidate_indices, assigned_history, candidates)
            ex = assignment(None, preferred_slot, assigned_history + candidates, topic['category'])
            try:
                source_docs, topic_errors = documents(root, sources_for(topic))
                errors.extend(topic_errors)
                candidate = generate_episode(model, source_docs, history(state, reserve) + candidates, ex['arm'], topic=topic)
                script_checks(candidate)
                editorial_checks(candidate, history(state, reserve)+candidates)
                if duplicate(candidate, history(state, reserve) + candidates):
                    raise ValueError('Candidate duplicates recent or reserved explanation')
                candidate['experiment'] = ex
                # This draft has passed factual/editorial checks, but is not a
                # publishable reserve until prepare completes all media checks.
                pending[candidate['id']] = {**copy.deepcopy(candidate), 'status':'reserved'}
                save(state_dir/'production.json', state)
                candidates.append(prepare(candidate, root, config))
            except Exception as exc:
                has_draft = any(d.get('topic_id') == topic['topic_id'] for d in pending.values())
                if not (has_draft and service_limits.blocked()):
                    for episode_id in [k for k, d in pending.items() if d.get('topic_id') == topic['topic_id']]:
                        pending.pop(episode_id)
                    release_topic(topic_ledger, topic['topic_id'], type(exc).__name__)
                save(state_dir/'production.json', state)
                errors.append({'brief': i, 'error': str(exc)[:160]})
                if not model.key or model.exhausted or service_limits.blocked():
                    break
        # Same-day reruns finish existing slots; they do not add another day's quota.
        needed = sum(s['id'] not in state['slots'] for s in plan_slots)
        ready = sum(r.get('status') == 'ready' for r in reserve)
        if len(candidates) + ready < needed:
            seed_reserve(root, config, docs, catalog, state, reserve, errors,
                         min(config['reserve_target'], needed - len(candidates)))
        selected_categories = {row.get('category', row.get('pillar')) for row in state['slots'].values()
                               if row['id'] in {s['id'] for s in plan_slots}}
        for planned in plan_slots:
            if planned['id'] in state['slots']:
                continue
            ordered = sorted(candidates, key=lambda c: (c.get('category') in selected_categories,
                             c['experiment']['slot_index'] != planned['slot_index']))
            episode = None
            for candidate in ordered:
                try:
                    # Candidates were already prepared before the next draft.
                    rendered_checks(candidate, root/'episodes'/candidate['id'], config)
                    episode = copy.deepcopy(candidate)
                    if episode['experiment']['slot_index'] != planned['slot_index']:
                        episode['experiment'] = {**episode['experiment'], 'id':'topic-slot-fallback-observational',
                                                'slot_index':planned['slot_index']}
                    candidates.remove(candidate)
                    break
                except Exception as exc:
                    pending.pop(candidate['id'], None)
                    release_topic(topic_ledger, candidate.get('topic_id'), type(exc).__name__)
                    errors.append({'candidate': candidate['id'], 'error': str(exc)[:160]})
                    candidates.remove(candidate)
            if episode is None:
                available = [r for r in reserve if r.get('status') == 'ready']
                available.sort(key=lambda r: r.get('category', r.get('pillar')) in selected_categories)
                for fallback in available:
                    try:
                        if duplicate(fallback,list(state['slots'].values())):
                            continue
                        rendered_checks(fallback, root/'episodes'/fallback['id'], config)
                        episode = copy.deepcopy(fallback)
                        # A pre-rendered reserve is observational, never falsely labelled randomized.
                        episode['experiment'] = {'id': 'reserve-observational', 'arm': 'reserve',
                            'slot_index': planned['slot_index'], 'promote_automatically': False}
                        fallback['status'] = 'allocated'
                        break
                    except Exception as exc:
                        errors.append({'reserve': fallback['id'], 'error': str(exc)[:160]})
            if episode is None:
                errors.append({'slot': planned['id'], 'error': 'No verified ready episode; no fabricated filler'})
                continue
            state['slots'][planned['id']] = {**episode, **planned, 'episode_id': episode['id'], 'status': 'prepared'}
            selected_categories.add(episode.get('category', episode.get('pillar')))
            pending.pop(episode['id'], None)
            sync_ledger(topic_ledger, [state['slots'][planned['id']]])
            save(state_dir/'production.json', state)
            save(root/'reserve.json', reserve)
        if mode == 'publish':
            from .youtube import YouTube, deliver
            from .state_io import checkpoint
            def persist():
                sync_ledger(topic_ledger, list(state['slots'].values()))
                save(state_dir/'production.json', state)
                checkpoint(root)
            persist()
            backend = YouTube()
            for row in state['slots'].values():
                if row['status'] == 'scheduled':
                    continue
                if parse(row['publish_at']) <= now():
                    # An overdue slot must not block unrelated future slots.
                    # Preserve its upload identity: an uncertain insert is never
                    # converted into an available topic or blindly re-uploaded.
                    row['recovery_required'] = 'missed_publish_time'
                    persist()
                    errors.append({'slot': row['id'], 'error': 'Missed publication time; reservation preserved'})
                    continue
                try:
                    row.pop('recovery_required', None)
                    episode = read(root/'episodes'/row['episode_id']/'episode.json')
                    if episode.get('production_version') != config['production_version']:
                        raise ValueError('Prepared slot uses an older production style')
                    rendered_checks(episode, root/'episodes'/row['episode_id'], config)
                    deliver(row, episode, root/'episodes'/row['episode_id'], backend,
                            persist)
                except Exception as exc:
                    errors.append({'slot': row['id'], 'error': str(exc)[:180]})
                    break  # Quota/uncertain upload: stop, keep prepared work for recovery.
        # Preserve unused generated candidates as reserves without regenerating audio later.
        for candidate in candidates:
            if sum(r.get('status') == 'ready' for r in reserve) >= config['reserve_target']:
                pending.pop(candidate['id'], None)
                release_topic(topic_ledger, candidate.get('topic_id'), 'reserve_full')
                continue
            try:
                episode = candidate
                reserve.append(episode)
                pending.pop(episode['id'], None)
                sync_ledger(topic_ledger, [episode])
                save(root/'reserve.json', reserve)
            except Exception as exc:
                pending.pop(candidate['id'], None)
                release_topic(topic_ledger, candidate.get('topic_id'), type(exc).__name__)
                errors.append({'reserve_build': candidate['id'], 'error': str(exc)[:160]})
        save(state_dir/'production.json', state)
        completed = sum(state['slots'].get(slot['id'], {}).get('status') ==
                        ('scheduled' if mode == 'publish' else 'prepared') for slot in plan_slots)
        recovery = [row['id'] for row in state['slots'].values() if row.get('recovery_required')]
        report = {'mode': mode, 'at': now().isoformat(), 'slots': len(state['slots']),
                  'planned_slots':len(plan_slots), 'completed_slots':completed,
                  'status':('needs_attention' if recovery else 'ready') if completed == len(plan_slots) else 'incomplete',
                  'recovery_slots':recovery,
                  'topics': {'total':len(bank), 'source_reviewed':sum(t.get('evidence_status')=='reviewed' for t in bank)},
                  'reserve_ready': sum(r.get('status') == 'ready' for r in reserve),
                  'pending_episodes': len(pending), 'errors': errors}
        save(root/'run-report.json', report)
        if mode == 'publish':
            from .state_io import checkpoint
            checkpoint(root)
        print(json.dumps(report, indent=2))
        if completed < len(plan_slots):
            raise DailyIncompleteError('Daily target incomplete; see run-report.json. Prepared work and upload reservations preserved.')
        if recovery:
            raise DailyIncompleteError('Current slots completed; overdue reservations require recovery. See run-report.json.')
        return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['preview','bootstrap','publish'], default='preview')
    parser.add_argument('--output')
    args = parser.parse_args()
    output = args.output or ('outputs/preview' if args.mode == 'preview' else 'outputs/credible')
    try:
        run(args.mode, Path(output))
    except DailyIncompleteError as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
