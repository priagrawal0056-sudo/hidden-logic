"""Compatibility interface for the reviewed everyday-topic bank.

idea_bank.json is retained as immutable legacy history. Selection does not consume
an idea; the production pipeline persists preparation and upload state separately.
"""
import argparse
from credible.core import read
from credible.topics import load_bank, shortlist, evidence_ready


def history():
    from credible.pipeline import history as production_history
    state = read('state/credible/production.json', {'slots': {}})
    rows = production_history(state, read('outputs/credible/reserve.json', []))
    return rows, state.get('topics', {})


def effective_bank():
    from credible.topic_review import reviewed_bank
    state = read('state/credible/production.json', {})
    return reviewed_bank(load_bank(), state.get('topic_reviews', {}))


def pick_unused(n, mark_used=True, log=print):
    rows, ledger = history()
    selected = shortlist(effective_bank(), rows, ledger, n=n)
    log(f'[idea_bank] {len(selected)} reviewed briefs selected; selection does not mark them published.')
    return [row['title'] for row in selected]


def remaining():
    rows, ledger = history()
    return len(shortlist(effective_bank(), rows, ledger, n=500))


def _is_dup_of_published(title, published):
    from credible.core import duplicate
    return duplicate({'title': title}, [{'title': p} for p in published]) is not None


def status():
    bank = effective_bank()
    print(f'{len(bank)} topic briefs; {sum(evidence_ready(t) for t in bank)} source-reviewed; '
          f'{remaining()} eligible distinct subjects now. Legacy bank unchanged.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--list', type=int, metavar='N')
    parser.add_argument('--import', dest='import_path')
    parser.add_argument('--reset-used', action='store_true')
    args = parser.parse_args()
    if args.reset_used or args.import_path:
        parser.error('Legacy resets and title-only imports are disabled. Review complete briefs in credible/topics.json.')
    if args.list is not None:
        for title in pick_unused(args.list, mark_used=False): print(title)
    else: status()


if __name__ == '__main__': main()
