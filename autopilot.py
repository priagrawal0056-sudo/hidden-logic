"""Evidence-led entry point. Legacy run_daily is not invoked."""
import sys
from credible.pipeline import run
from pathlib import Path

if __name__ == '__main__':
    preview = '--dry-run' in sys.argv
    run('preview' if preview else 'publish',
        Path('outputs/preview' if preview else 'outputs/credible'))
