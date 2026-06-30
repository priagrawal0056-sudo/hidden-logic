"""
ab_report.py - Compare A/B script-variant performance before committing.

Reads ab_log.json (written by run_daily after each upload: video_id -> {variant, title,
date}), pulls each video's average view percentage (retention) from YouTube Analytics, and
prints the average retention per variant plus a recommendation.

Why retention and not views: Shorts view counts are dominated by the explore/exploit
lottery (one video does 50k, most do a few hundred), so they are far too noisy to compare
small samples. Average view percentage (how much of the video people actually watch) is the
cleanest signal of whether a script holds attention, and it is exactly what the variants are
trying to move.

Usage:
    python ab_report.py            # uses last 28 days of retention data
    python ab_report.py --days 14  # narrower window

Honest caveats this prints too: small samples are noisy; let it run until each variant has a
healthy number of videos (aim for 20+ each) before trusting the result; retention also drifts
with topic mix, so this is a guide, not proof.
"""
import argparse
import json
import math
import os
import statistics
import sys


def welch_t_test(a: list, b: list):
    """Welch's t-test for two samples with unequal variance (no scipy needed). Returns
    (t, df, p_two_sided) or None if the samples are too small/degenerate. The p-value uses
    a normal approximation, which is fine for the sample sizes this report needs (>=~12)."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return None
    ma, mb = statistics.mean(a), statistics.mean(b)
    va, vb = statistics.variance(a), statistics.variance(b)
    se = math.sqrt(va / na + vb / nb)
    if se == 0:
        return None
    t = (mb - ma) / se
    denom = (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)
    df = ((va / na + vb / nb) ** 2 / denom) if denom > 0 else (na + nb - 2)
    try:
        p = 2 * (1 - statistics.NormalDist().cdf(abs(t)))
    except Exception:
        p = None
    return t, df, p


def _load_log(path="ab_log.json"):
    if not os.path.exists(path):
        print("No ab_log.json found yet. Turn on the A/B test (set \"script_ab\": true in "
              "config.json) and run some videos first.")
        sys.exit(0)
    with open(path) as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28, help="retention window in days")
    ap.add_argument("--min-each", type=int, default=12,
                    help="videos per variant (with data) before the result is considered trustworthy")
    ap.add_argument("--alpha", type=float, default=0.05, help="two-sided significance threshold")
    ap.add_argument("--commit", action="store_true",
                    help="if a variant wins SIGNIFICANTLY, write it to config.json (script_ab=false, script_variant=winner)")
    args = ap.parse_args()

    log = _load_log()
    if not log:
        print("ab_log.json is empty. Run some videos with the A/B test on first.")
        return

    try:
        import upload
    except Exception as e:
        print(f"Could not import upload.py (needed for retention data): {e}")
        return

    ids = list(log.keys())
    retention = upload.video_retention(ids, days=args.days)
    if not retention:
        print("No retention data came back from YouTube Analytics. Videos may be too new "
              "(retention needs a few days of views), or analytics auth failed.")
        return

    # bucket retention by variant
    buckets = {"A": [], "B": []}
    counted = {"A": 0, "B": 0}
    for vid, info in log.items():
        v = info.get("variant", "A")
        if v not in buckets:
            continue
        counted[v] += 1
        if vid in retention:
            buckets[v].append(retention[vid])

    print(f"\n=== A/B SCRIPT VARIANT REPORT (last {args.days} days) ===\n")
    print("  A = current prompt")
    print("  B = current + modern-mirror + hidden-truth techniques\n")

    summary = {}
    for v in ("A", "B"):
        vals = buckets[v]
        if vals:
            avg = statistics.mean(vals)
            med = statistics.median(vals)
            summary[v] = avg
            print(f"  Variant {v}: {len(vals)} videos with data "
                  f"(of {counted[v]} uploaded)")
            print(f"     avg retention:    {avg:.1f}%")
            print(f"     median retention: {med:.1f}%\n")
        else:
            print(f"  Variant {v}: no retention data yet "
                  f"(of {counted[v]} uploaded)\n")

    # verdict — now gated on a real significance test, not just a raw mean difference
    if "A" in summary and "B" in summary:
        a_vals, b_vals = buckets["A"], buckets["B"]
        diff = summary["B"] - summary["A"]
        n_each = min(len(a_vals), len(b_vals))
        enough = n_each >= args.min_each
        tt = welch_t_test(a_vals, b_vals)
        print("  ----------------------------------------")
        if tt:
            t, df, p = tt
            psig = (p is not None and p < args.alpha)
            ptxt = f"p={p:.3f}" if p is not None else "p=n/a"
            print(f"  Welch t-test: t={t:+.2f}, df={df:.0f}, {ptxt} (alpha={args.alpha})")
        else:
            psig = False
            print("  Welch t-test: not enough data to compute.")
        significant = bool(enough and psig and abs(diff) >= 1.0)
        if not enough:
            print(f"  WARNING: sample still small (have {n_each}/variant, need {args.min_each}). NOT trustworthy yet.")
        winner = "B" if diff > 0 else "A"
        if significant:
            print(f"  VERDICT: Variant {winner} wins by {abs(diff):.1f} retention points - STATISTICALLY SIGNIFICANT.")
        elif abs(diff) < 1.0:
            print(f"  VERDICT: basically tied ({diff:+.1f}% for B). No winner.")
        else:
            print(f"  VERDICT: {winner} leads by {abs(diff):.1f} pts, but NOT significant - keep running.")
        print("  ----------------------------------------")
        if significant:
            if args.commit:
                try:
                    with open("config.json", encoding="utf-8") as f:
                        cfg = json.load(f)
                    cfg["script_ab"] = False
                    cfg["script_variant"] = winner
                    with open("config.json", "w", encoding="utf-8") as f:
                        json.dump(cfg, f, indent=2)
                    print(f"\n  COMMITTED: set script_ab=false, script_variant={winner} in config.json.")
                except Exception as e:
                    print(f"\n  Could not auto-commit ({e}). Manually set script_ab=false, script_variant={winner}.")
            else:
                print(f"\n  To COMMIT variant {winner}: re-run with --commit (or set script_ab=false, script_variant={winner}).")
    else:
        print("  Not enough data on both variants yet to compare. Keep running.")
    print()


if __name__ == "__main__":
    main()
