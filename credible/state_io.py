"""Explicit state files only. A failed checkpoint prevents the next upload action."""
import os
import shutil
import subprocess
from pathlib import Path

FILES = ('production.json', 'analytics.json', 'legacy_analytics.json',
         'experiment_report.json', 'reserve.json', 'discovery.json', 'pilot_review.json', 'used_clips.json')


def checkpoint(root='outputs/credible'):
    state = Path('state/credible')
    state.mkdir(parents=True, exist_ok=True)
    reserve = Path(root)/'reserve.json'
    if reserve.exists():
        shutil.copyfile(reserve, state/'reserve.json')
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        return
    paths = [str(state/name).replace('\\','/') for name in FILES if (state/name).exists()]
    if not paths:
        return
    run = lambda *args: subprocess.run(['git', *args], check=True, capture_output=True, text=True)
    run('config', 'user.name', 'hidden-logic-bot')
    run('config', 'user.email', 'bot@users.noreply.github.com')
    run('add', '--', *paths)
    changed = subprocess.run(['git','diff','--cached','--quiet'], capture_output=True)
    if changed.returncode not in (0,1):
        raise RuntimeError('Cannot inspect staged state')
    staged = run('diff','--cached','--name-only').stdout.splitlines()
    if not set(staged) <= set(paths):
        raise RuntimeError('Refusing to commit files outside explicit state allowlist')
    if changed.returncode == 1:
        run('commit','-m','Update verified Shorts production state')
    # No rebasing/merging mutable ledgers automatically. Shared workflow concurrency
    # prevents normal writer races; unexpected branch movement fails visibly.
    branch = os.environ.get('GITHUB_REF_NAME', 'main')
    # Retry the push even with a clean index: a previous checkpoint may have
    # committed locally and then failed to push its upload ledger.
    run('push','origin', 'HEAD:' + branch)


if __name__ == '__main__':
    checkpoint()
