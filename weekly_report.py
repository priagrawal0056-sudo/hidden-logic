"""
weekly_report.py - reads the channel's accumulated analytics and explains, in plain English,
what is actually working and what is dying. This closes the learning loop: instead of staring
at raw numbers, you get "here's what to make more of and what to stop making."

It uses two data sources you already have:
  - analytics_memory.json : per-CLUSTER averages (stay%, AVD, views, engagement)
  - ab_log.json           : per-VIDEO data (AVD, views, title, hook_type, cluster)

The single most useful signal here is RETENTION (stay% and AVD relative to video length),
because views are capped by retention - a video only spreads if people stay. So the report
leads with retention, then views, then engagement.

Run:
    python weekly_report.py            # prints the report
    python weekly_report.py --save     # also writes weekly_report.txt
"""
import json
import os
import sys
import datetime as dt

ANALYTICS = "analytics_memory.json"
AB_LOG = "ab_log.json"
CHANNEL_INDEX = "channel_index.json"


def _load(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def _fmt(x, suffix="", nd=0):
    if x is None:
        return "n/a"
    return f"{x:.{nd}f}{suffix}"


def cluster_retention_table(analytics):
    """Build a retention-ranked view of clusters that actually have stay% data."""
    rows = []
    for cl, d in analytics.get("clusters", {}).items():
        stay = d.get("avg_stayed_to_watch")
        avd = d.get("avg_avd")
        v24 = d.get("avg_views_first_24h")
        cnt = d.get("count", 0)
        if stay is not None or avd is not None:
            rows.append({
                "cluster": cl, "stay": stay, "avd": avd, "views": v24, "count": cnt,
            })
    # rank by stay% (retention is the lever); fall back to AVD when stay is missing
    rows.sort(key=lambda r: (r["stay"] if r["stay"] is not None else (r["avd"] or 0)), reverse=True)
    return rows


def per_video_signals(ab_log):
    """Extract per-video AVD-based retention signals. AVD/length is the cleanest per-video
    retention proxy available (a 30s video held to 18s = strong; to 9s = weak)."""
    vids = []
    for vid, info in ab_log.items():
        if not isinstance(info, dict):
            continue
        avd = info.get("avd")
        # 'retention' was historically never written to ab_log; stayed_to_watch is the real
        # field, so fall back to it instead of silently under-reporting every video.
        ret = info.get("retention")
        if ret is None:
            ret = info.get("stayed_to_watch")
        title = info.get("title", "")
        hook = info.get("hook_type", "")
        cluster = info.get("cluster", "")
        if avd is not None or ret is not None:
            vids.append({
                "id": vid, "title": title, "avd": avd, "retention": ret,
                "hook": hook, "cluster": cluster,
            })
    return vids


def hook_retention(vids):
    """Average AVD by hook type, to see which opening style holds viewers."""
    by_hook = {}
    for v in vids:
        if v["avd"] is None or not v["hook"]:
            continue
        by_hook.setdefault(v["hook"], []).append(v["avd"])
    out = []
    for hook, lst in by_hook.items():
        out.append({"hook": hook, "avg_avd": round(sum(lst) / len(lst), 1), "n": len(lst)})
    out.sort(key=lambda x: -x["avg_avd"])
    return out


def build_report(save=False):
    analytics = _load(ANALYTICS, {})
    ab_log = _load(AB_LOG, {})
    lines = []
    W = lines.append

    W("=" * 60)
    W(f"  HIDDEN LOGIC - WEEKLY INSIGHT REPORT")
    W(f"  {dt.date.today().isoformat()}")
    W("=" * 60)
    W("")

    # ---- RETENTION (the lever) ----
    rows = cluster_retention_table(analytics)
    if not rows:
        W("RETENTION: not enough data yet. Keep running - the analytics poll needs")
        W("videos that are 2-14 days old to compute stay-rate. Check back in a few days.")
    else:
        W("RETENTION BY TOPIC TYPE (this is what caps your views):")
        W(f"  {'topic':18} {'stay%':>6} {'avd(s)':>7} {'views/24h':>10} {'n':>3}")
        for r in rows:
            W(f"  {r['cluster']:18} {_fmt(r['stay'],'%',1):>6} "
              f"{_fmt(r['avd'],'',1):>7} {_fmt(r['views'],'',0):>10} {r['count']:>3}")
        W("")
        # plain-English read
        best = rows[0]
        worst = rows[-1]
        if best["stay"] is not None:
            if best["stay"] >= 50:
                W(f"  -> '{best['cluster']}' holds {best['stay']:.0f}% of viewers - that's above the")
                W(f"     ~50% bar YouTube wants. Topics like this earn distribution. Make more.")
            else:
                W(f"  -> Even your best ('{best['cluster']}', {best['stay']:.0f}%) is under the ~50%")
                W(f"     retention bar. The bottleneck is the first few seconds / the voice, not topics.")
            if worst["stay"] is not None and worst["cluster"] != best["cluster"]:
                W(f"  -> '{worst['cluster']}' only holds {worst['stay']:.0f}% - these die early. Make fewer,")
                W(f"     or rework how they open.")
    W("")

    # ---- HOOK PERFORMANCE ----
    vids = per_video_signals(ab_log)
    hooks = hook_retention(vids)
    if hooks:
        W("OPENING HOOK STYLE (avg seconds watched - higher = holds better):")
        for h in hooks:
            W(f"  {h['hook']:18} {h['avg_avd']:>5.1f}s   ({h['n']} videos)")
        if len(hooks) >= 2:
            W(f"  -> '{hooks[0]['hook']}' openings hold longest. Lean into that style.")
        W("")

    # ---- TOP & BOTTOM VIDEOS BY RETENTION ----
    rated = [v for v in vids if v["avd"] is not None]
    if rated:
        rated.sort(key=lambda v: -v["avd"])
        W("VIDEOS THAT HELD VIEWERS LONGEST (study these - copy what they do):")
        for v in rated[:5]:
            W(f"  {v['avd']:>5.1f}s  {v['title'][:50]}")
        if len(rated) > 6:
            W("")
            W("VIDEOS THAT LOST VIEWERS FASTEST (what went wrong here?):")
            for v in rated[-5:]:
                W(f"  {v['avd']:>5.1f}s  {v['title'][:50]}")
        W("")

    # ---- THE BOTTOM LINE ----
    W("-" * 60)
    W("BOTTOM LINE:")
    if rows and rows[0]["stay"] is not None and rows[0]["stay"] >= 50:
        W("  Your best topics already retain well. The ceiling now is reach, not")
        W("  retention on those - which means: keep making the high-stay topic types,")
        W("  and the single biggest remaining lever is a more human-sounding voice.")
    elif rows:
        W("  Retention is still the bottleneck. Before more topic changes, the wins are")
        W("  in the first 3 seconds (hook) and the voice. Those move stay-rate most.")
    else:
        W("  Not enough retention data yet - let the pipeline run another week, then")
        W("  this report will tell you exactly which topic types and hooks to double down on.")
    W("=" * 60)

    report = "\n".join(lines)
    print(report)
    if save:
        with open("weekly_report.txt", "w", encoding="utf-8") as f:
            f.write(report)
        print("\n(Saved to weekly_report.txt)")
    return report


if __name__ == "__main__":
    build_report(save="--save" in sys.argv[1:])
