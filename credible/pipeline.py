from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .core import assignment, duplicate, lock, now, read, save, slots, digest, file_hash
from .evidence import FreeModel, generate_episode, retrieve, verify_support
from .media import render, synthesize
from .quality import rendered_checks, script_checks, timeline_checks, editorial_checks
from .seeds import RECIPES, build_recipe


def settings():
    return read('credible/settings.json')


def documents(root, catalog):
    result, errors = {}, []
    snapshots = {s['url']: s for s in read('credible/source_snapshots.json', [])}
    for source in catalog:
        try:
            result[source['url']] = retrieve(source, root / 'evidence')
        except Exception as exc:
            errors.append({'source': source['id'], 'error': type(exc).__name__})
            if source['url'] in snapshots:
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
    narration_signature = digest([episode['beats'],config['voice'],config.get('voice_rate')])
    renderer_signature = digest([(name,file_hash(Path(__file__).parent/name))
                                for name in ('media.py','storyboard.py','quality.py')])
    signature = digest([narration_signature,episode['storyboard'],episode['evidence'],episode['source_label'],
                        config['width'],config['height'],config['fps'],config['production_version'],renderer_signature])
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
            and (folder/'voice.mp3').exists() and file_hash(folder/'voice.mp3')==voice_asset['sha256']):
        for key in ('duration','scenes','captions','voice','assets'):
            episode[key]=copy.deepcopy(previous[key])
    else:
        episode = synthesize(episode, folder, config)
    timeline_checks(episode, folder, config)
    episode.pop('quality', None)
    render(episode, folder, config)
    episode['quality'] = rendered_checks(episode, folder, config)
    episode['render_version'] = config['production_version']
    episode['render_signature'] = signature
    episode['narration_signature'] = narration_signature
    episode['status'] = 'ready'
    save(folder / 'episode.json', episode)
    return episode


def history(state, reserve):
    legacy = read('channel_index.json', [])
    return legacy + list(state['slots'].values()) + [r for r in reserve if r.get('status') in ('ready','needs_rebuild')]


def seed_reserve(root, config, docs, catalog, state, reserve, errors, limit=9):
    sources = {s['id']: s for s in catalog}
    for recipe in RECIPES:
        if len([r for r in reserve if r.get('status') == 'ready']) >= limit:
            break
        source = sources[recipe[0]]
        if source['url'] not in docs:
            continue
        try:
            episode = build_recipe(recipe, source, docs[source['url']])
            if duplicate(episode, history(state, reserve)):
                continue
            verify_support(episode['evidence'], docs)
            episode = prepare(episode, root, config)
            reserve.append(episode)
            save(root / 'reserve.json', reserve)
            print('Prepared reserve:', episode['title'], flush=True)
        except Exception as exc:
            errors.append({'candidate': recipe[0], 'error': str(exc)[:180]})
            print('Reserve unavailable:', recipe[0], type(exc).__name__, flush=True)


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
    with lock(state_dir / 'pipeline.lock'):
        state = read(state_dir / 'production.json', {'schema_version': 2, 'slots': {}})
        reserve = read(root / 'reserve.json', [])
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
        if mode != 'bootstrap':
            from .discovery import discover
            catalog += discover(catalog, root/'evidence', state_dir/'discovery.json')
        docs, source_errors = documents(root, catalog)
        errors.extend(source_errors)
        # Bootstrap renders require no model key. They are also the quota fallback.
        seed_reserve(root, config, docs, catalog, state, reserve, errors, config['reserve_target'])
        if mode == 'bootstrap':
            save(root / 'run-report.json', {'reserve_ready': sum(r.get('status') == 'ready' for r in reserve), 'errors': errors})
            return reserve
        model = FreeModel(config)
        candidates = []
        run_day = now().astimezone(ZoneInfo(config['timezone'])).date().isoformat()
        plan_slots = state.setdefault('run_days', {}).get(run_day)
        if plan_slots is None:
            plan_slots = slots(config)
            state['run_days'][run_day] = plan_slots
            save(state_dir/'production.json', state)
        # Six briefs, two per pillar. Small bounded calls; do not grind quota retries.
        for i in range(config['briefs_per_day']):
            pillar = ('technology','travel','shopping')[i % 3]
            source_docs = {s['url']: docs[s['url']] for s in catalog
                           if s['pillar'] == pillar and s['url'] in docs and not docs[s['url']].get('snapshot_only')}
            # Rotate the retrieved corpus so the same opening paragraphs do not dominate.
            items = list(source_docs.items())
            offset = (now().toordinal() + i) % max(1,len(items))
            source_docs = dict((items[offset:] + items[:offset])[:3])
            ex = assignment(pillar, i % 3, list(state['slots'].values()) + candidates)
            try:
                candidate = generate_episode(model, source_docs, history(state, reserve) + candidates, ex['arm'])
                script_checks(candidate)
                editorial_checks(candidate, history(state, reserve)+candidates)
                if duplicate(candidate, history(state, reserve) + candidates):
                    continue
                candidate['experiment'] = ex
                candidates.append(candidate)
            except Exception as exc:
                errors.append({'brief': i, 'error': str(exc)[:160]})
                if not model.key or model.exhausted:
                    break
        # Same-day reruns finish existing slots; they do not add another day's quota.
        for planned in plan_slots:
            if planned['id'] in state['slots']:
                continue
            preferred = ('technology','travel','shopping')[planned['slot_index']]
            ordered = [c for c in candidates if c['pillar'] == preferred]
            episode = None
            for candidate in ordered:
                try:
                    episode = prepare(candidate, root, config)
                    candidates.remove(candidate)
                    break
                except Exception as exc:
                    errors.append({'candidate': candidate['id'], 'error': str(exc)[:160]})
                    candidates.remove(candidate)
            if episode is None:
                available = [r for r in reserve if r.get('status') == 'ready']
                available.sort(key=lambda r: r['pillar'] != preferred)
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
            save(state_dir/'production.json', state)
            save(root/'reserve.json', reserve)
        if mode == 'publish':
            from .youtube import YouTube, deliver
            from .state_io import checkpoint
            def persist():
                save(state_dir/'production.json', state)
                checkpoint(root)
            persist()
            backend = YouTube()
            for row in state['slots'].values():
                if row['status'] == 'scheduled':
                    continue
                try:
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
                break
            try:
                episode = prepare(candidate, root, config)
                reserve.append(episode)
                save(root/'reserve.json', reserve)
            except Exception as exc:
                errors.append({'reserve_build': candidate['id'], 'error': str(exc)[:160]})
        report = {'mode': mode, 'at': now().isoformat(), 'slots': len(state['slots']),
                  'reserve_ready': sum(r.get('status') == 'ready' for r in reserve), 'errors': errors}
        save(root/'run-report.json', report)
        if mode == 'publish':
            from .state_io import checkpoint
            checkpoint(root)
        print(json.dumps(report, indent=2))
        return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['preview','bootstrap','publish'], default='preview')
    parser.add_argument('--output')
    args = parser.parse_args()
    output = args.output or ('outputs/preview' if args.mode == 'preview' else 'outputs/credible')
    run(args.mode, Path(output))


if __name__ == '__main__':
    main()
