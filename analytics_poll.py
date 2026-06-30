import os
import json
import datetime
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import upload

AB_LOG_PATH = "ab_log.json"
ANALYTICS_MEMORY_PATH = "analytics_memory.json"

def parse_iso_datetime(dt_str: str) -> datetime.datetime:
    """Parse UTC ISO datetime string (e.g. 2026-06-23T15:00:00Z) to timezone-aware datetime."""
    try:
        val = dt_str.replace("Z", "+00:00")
        dt_obj = datetime.datetime.fromisoformat(val)
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=datetime.timezone.utc)
        return dt_obj
    except Exception:
        return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

def aggregate_analytics(ab_log: dict):
    """Aggregate stats per topic, cluster, subcluster, and hook type."""
    groups = {
        "topics": {},
        "clusters": {},
        "subclusters": {},
        "hook_types": {}
    }

    # Help compute averages
    def add_to_group(group_key, item_key, data):
        if not item_key:
            return
        g = groups[group_key]
        if item_key not in g:
            g[item_key] = {
                "count": 0,
                "views_first_60m_list": [],
                "views_first_6h_list": [],
                "views_first_24h_list": [],
                "stayed_to_watch_list": [],
                "avd_list": [],
                "comments_per_1000_views_list": [],
                "likes_per_1000_views_list": [],
                "returning_viewers_list": []
            }
        entry = g[item_key]
        entry["count"] += 1
        if data.get("views_first_60m") is not None:
            entry["views_first_60m_list"].append(data["views_first_60m"])
        if data.get("views_first_6h") is not None:
            entry["views_first_6h_list"].append(data["views_first_6h"])
        if data.get("views_first_24h") is not None:
            entry["views_first_24h_list"].append(data["views_first_24h"])
        if data.get("stayed_to_watch") is not None:
            entry["stayed_to_watch_list"].append(data["stayed_to_watch"])
        if data.get("avd") is not None:
            entry["avd_list"].append(data["avd"])
        if data.get("comments_per_1000_views") is not None:
            entry["comments_per_1000_views_list"].append(data["comments_per_1000_views"])
        if data.get("likes_per_1000_views") is not None:
            entry["likes_per_1000_views_list"].append(data["likes_per_1000_views"])
        if data.get("returning_viewers") is not None:
            entry["returning_viewers_list"].append(data["returning_viewers"])

    for video_id, info in ab_log.items():
        add_to_group("topics", info.get("topic"), info)
        add_to_group("clusters", info.get("cluster"), info)
        add_to_group("subclusters", info.get("subcluster"), info)
        add_to_group("hook_types", info.get("hook_type"), info)

    # Compute averages
    memory = {}
    for group_key, items in groups.items():
        memory[group_key] = {}
        for item_key, entry in items.items():
            def avg(lst):
                return round(sum(lst) / len(lst), 1) if lst else None
            
            memory[group_key][item_key] = {
                "count": entry["count"],
                "avg_views_first_60m": avg(entry["views_first_60m_list"]),
                "avg_views_first_6h": avg(entry["views_first_6h_list"]),
                "avg_views_first_24h": avg(entry["views_first_24h_list"]),
                "avg_stayed_to_watch": avg(entry["stayed_to_watch_list"]),
                "avg_avd": avg(entry["avd_list"]),
                "avg_comments_per_1000_views": avg(entry["comments_per_1000_views_list"]),
                "avg_likes_per_1000_views": avg(entry["likes_per_1000_views_list"]),
                "avg_returning_viewers": avg(entry["returning_viewers_list"])
            }

    with open(ANALYTICS_MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2)
    print(f"[analytics_poll] Aggregated performance stats written to {ANALYTICS_MEMORY_PATH}")

def main():
    if not os.path.exists(AB_LOG_PATH):
        print(f"[analytics_poll] No {AB_LOG_PATH} found. Skipping poll.")
        return

    with open(AB_LOG_PATH, encoding="utf-8") as f:
        ab_log = json.load(f)

    now = datetime.datetime.now(datetime.timezone.utc)
    recent_video_ids = []
    analytics_video_ids = []
    engagement_video_ids = []

    for video_id, info in ab_log.items():
        publish_at_str = info.get("publish_at")
        if not publish_at_str:
            continue
        
        pub_dt = parse_iso_datetime(publish_at_str)
        elapsed_hours = (now - pub_dt).total_seconds() / 3600.0

        # Poll views for videos published within the last 30 hours
        if 0 < elapsed_hours <= 30.0:
            if (
                (elapsed_hours >= 1.0 and info.get("views_first_60m") is None) or
                (elapsed_hours >= 6.0 and info.get("views_first_6h") is None) or
                (elapsed_hours >= 24.0 and info.get("views_first_24h") is None)
            ):
                recent_video_ids.append(video_id)

        # Pull Analytics API retention and AVD for videos between 2 days and 14 days old.
        # Retention/AVD are noisy/empty in the first hours and only settle after ~2 days. BUG
        # FIX: this used to compare elapsed_HOURS to 2-14, so it polled at 2-14 hours (garbage
        # window) and NEVER in the intended 2-14 day window - which is why almost no videos had
        # real retention data.
        if 2.0 * 24.0 <= elapsed_hours <= 14.0 * 24.0:
            if info.get("avd") is None or info.get("retention") is None:
                analytics_video_ids.append(video_id)

        # Collect all videos published in the last 30 days for engagement rates polling
        if 0 < elapsed_hours <= 30.0 * 24.0:
            engagement_video_ids.append(video_id)

    # 1. Fetch views, likes, and comments for videos published in the last 30 days
    stats = {}
    if engagement_video_ids:
        print(f"[analytics_poll] Fetching statistics for {len(engagement_video_ids)} videos published in the last 30 days...")
        for i in range(0, len(engagement_video_ids), 50):
            chunk = engagement_video_ids[i:i+50]
            try:
                stats.update(upload.video_stats(chunk))
            except Exception as e:
                print(f"[analytics_poll] Failed to query video stats: {e}")

        # Update engagement rates and early views milestones
        for video_id in engagement_video_ids:
            if video_id not in stats:
                continue
            s = stats[video_id]
            views = s.get("viewCount", 0)
            likes = s.get("likeCount", 0)
            comments = s.get("commentCount", 0)
            info = ab_log[video_id]

            if views > 0:
                info["comments_per_1000_views"] = round((comments / views) * 1000.0, 2)
                info["likes_per_1000_views"] = round((likes / views) * 1000.0, 2)
            else:
                info["comments_per_1000_views"] = 0.0
                info["likes_per_1000_views"] = 0.0

            # Update early views milestones
            if video_id in recent_video_ids:
                pub_dt = parse_iso_datetime(info.get("publish_at"))
                elapsed_hours = (now - pub_dt).total_seconds() / 3600.0

                if elapsed_hours >= 1.0 and info.get("views_first_60m") is None:
                    info["views_first_60m"] = views
                    print(f"  - {info.get('title')[:30]}... 60m views: {views}")
                if elapsed_hours >= 6.0 and info.get("views_first_6h") is None:
                    info["views_first_6h"] = views
                    print(f"  - {info.get('title')[:30]}... 6h views: {views}")
                if elapsed_hours >= 24.0 and info.get("views_first_24h") is None:
                    info["views_first_24h"] = views
                    print(f"  - {info.get('title')[:30]}... 24h views: {views}")

    # 2. Fetch YouTube Analytics API retention/AVD
    if analytics_video_ids:
        print(f"[analytics_poll] Querying YouTube Analytics for {len(analytics_video_ids)} videos...")
        try:
            analytics_data = upload.video_analytics(analytics_video_ids)
            for video_id, data in analytics_data.items():
                if video_id in ab_log:
                    ab_log[video_id]["avd"] = data["avd"]
                    ab_log[video_id]["retention"] = data["retention"]
                    print(f"  - {ab_log[video_id].get('title')[:30]}... AVD: {data['avd']}s, Retention: {data['retention']}%")
        except Exception as e:
            print(f"[analytics_poll] Failed to query YouTube Analytics: {e}")

    # Save log
    with open(AB_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(ab_log, f, indent=2)
    print(f"[analytics_poll] Saved updates to {AB_LOG_PATH}")

    # Re-calculate aggregates
    aggregate_analytics(ab_log)

if __name__ == "__main__":
    main()
