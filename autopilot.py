"""
autopilot.py - ONE command, zero decisions. The system does everything.

    python autopilot.py

That's it. With no input from you, the system:
  1. Auto-picks today's single highest-potential topic (morning brief: trends + analytics
     + scored ideas) and makes it video #1 of the day.
  2. Fills the rest of the day's quota (videos_per_day in config.json) from the trend-aware
     auto pool - it picks those topics itself too.
  3. Scripts, gates, voices, captions, fetches b-roll, renders, and uploads each video on a
     staggered schedule, seeds the first comment, replies to comments, and sends the digest.

No topic to choose, no script to write, no button to press. Walk away.

This is a thin wrapper around 'run_daily.py --hero' so you have one obvious command to run
(and one obvious thing for Task Scheduler to launch). Pass --dry-run to build without uploading.
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
