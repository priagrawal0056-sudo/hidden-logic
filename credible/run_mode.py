"""Resolve scheduled/manual work before loading credentials or paid dependencies."""
import argparse
import json
import os
from pathlib import Path

from .core import now, save


def resolve(event, requested, rollout_enabled):
    if type(rollout_enabled) is not bool:
        raise ValueError('rollout_enabled must be a boolean')
    if event not in ('schedule', 'workflow_dispatch'):
        raise ValueError('Unsupported workflow event')
    mode = 'publish' if event == 'schedule' else requested or 'preview'
    if mode not in ('preview', 'bootstrap', 'publish'):
        raise ValueError('Unsupported generation mode')
    if mode == 'publish' and not rollout_enabled:
        scheduled = event == 'schedule'
        return {'run': False, 'mode': mode,
                'status': 'skipped_rollout' if scheduled else 'blocked_rollout',
                'exit_code': 0 if scheduled else 1,
                'reason': 'YouTube publishing is disabled pending finished-pilot approval. '
                          'No generation or upload was attempted.'}
    return {'run': True, 'mode': mode, 'status': 'allowed', 'exit_code': 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--event', default=os.environ.get('WORKFLOW_EVENT', 'workflow_dispatch'))
    parser.add_argument('--mode', default=os.environ.get('REQUESTED_MODE', ''))
    parser.add_argument('--settings', type=Path, default=Path('credible/settings.json'))
    parser.add_argument('--report', type=Path, default=Path('outputs/credible/run-report.json'))
    args = parser.parse_args()
    config = json.loads(args.settings.read_text(encoding='utf-8'))
    decision = resolve(args.event, args.mode, config['rollout_enabled'])
    if not decision['run']:
        save(args.report, {**decision, 'at': now().isoformat(), 'published': False,
                           'completed_slots': 0, 'errors': [] if not decision['exit_code'] else [decision['reason']]})
        print(decision['reason'])
        print('Scheduled run skipped normally.' if not decision['exit_code'] else 'Requested publishing remains blocked.')
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a', encoding='utf-8') as stream:
            stream.write('run=' + str(decision['run']).lower() + '\nmode=' + decision['mode'] + '\n')
    return decision['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
