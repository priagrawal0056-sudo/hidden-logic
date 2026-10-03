"""
autopilot.py - one entry point for the existing daily Hidden Logic pipeline.

The normal topic, script, evidence, voice, footage, caption, rendering, analytics, and upload
integrations remain in run_daily.py. Uploads are fail-closed: rollout_enabled and
pilot_review_complete must both be explicitly approved after the six unpublished pilots pass
human review. Pass --dry-run to create private local drafts without uploading.
"""
import os
import subprocess
import sys


def main():
    py = sys.executable or "python"
    here = os.path.dirname(os.path.abspath(__file__)) or "."
    cmd = [py, "-u", "run_daily.py", "--hero"]
    if "--dry-run" in sys.argv:
        cmd.append("--dry-run")
    print("=" * 60)
    print("  HIDDEN LOGIC - FULL AUTOPILOT (no input needed)")
    print("=" * 60)
    raise SystemExit(subprocess.run(cmd, cwd=here).returncode)


if __name__ == "__main__":
    main()
