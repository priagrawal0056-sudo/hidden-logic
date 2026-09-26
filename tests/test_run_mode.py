import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from credible.run_mode import resolve


class RunModeTests(unittest.TestCase):
    def test_disabled_schedule_skips_but_explicit_publish_is_blocked(self):
        scheduled = resolve('schedule', '', False)
        self.assertFalse(scheduled['run'])
        self.assertEqual(scheduled['status'], 'skipped_rollout')
        self.assertEqual(scheduled['exit_code'], 0)
        self.assertEqual(resolve('workflow_dispatch', 'publish', False)['exit_code'], 1)

    def test_preview_and_bootstrap_are_available_without_rollout(self):
        for mode in ('preview', 'bootstrap'):
            result = resolve('workflow_dispatch', mode, False)
            self.assertTrue(result['run'])
            self.assertEqual(result['mode'], mode)
        self.assertEqual(resolve('workflow_dispatch', '', False)['mode'], 'preview')
        self.assertEqual(resolve('schedule', '', True)['mode'], 'publish')

    def test_invalid_configuration_cannot_enable_publishing(self):
        for flag in ('false', None, 1):
            with self.assertRaises(ValueError): resolve('schedule', '', flag)
        with self.assertRaises(ValueError): resolve('push', '', False)
        with self.assertRaises(ValueError): resolve('workflow_dispatch', 'typo', False)

    def test_real_preflight_process_skips_without_touching_saved_work(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder/'settings.json').write_text('{"rollout_enabled": false}')
            sentinel = folder/'production.json'
            sentinel.write_bytes(b'saved upload reservation')
            env = {k:v for k,v in os.environ.items() if not k.startswith('HL_')}
            env['GITHUB_OUTPUT'] = str(folder/'github-output.txt')
            result = subprocess.run([sys.executable, '-B', '-m', 'credible.run_mode',
                '--event', 'schedule', '--settings', str(folder/'settings.json'),
                '--report', str(folder/'report.json')], cwd=root, env=env,
                capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((folder/'report.json').read_text())
            self.assertEqual(report['status'], 'skipped_rollout')
            self.assertFalse(report['published'])
            self.assertEqual(sentinel.read_bytes(), b'saved upload reservation')
            self.assertIn('run=false', (folder/'github-output.txt').read_text())

    def test_workflow_gates_credentials_generation_and_cache_writes(self):
        # Guard wiring as well as the helper: a skipped schedule must not save
        # an empty reserve cache over the last usable one.
        workflow = (Path(__file__).resolve().parents[1]/'.github/workflows/daily.yml').read_text()
        steps = workflow.split('      - ')
        for marker in ('Restore YouTube credentials', 'Produce Shorts',
                       'Persist explicit state files', 'actions/cache/save@v4'):
            matched = [step for step in steps if step.startswith('name: '+marker) or step.startswith('uses: '+marker)]
            self.assertTrue(matched, marker)
            self.assertTrue(all("steps.mode.outputs.run == 'true'" in step for step in matched), marker)


if __name__ == '__main__': unittest.main()
