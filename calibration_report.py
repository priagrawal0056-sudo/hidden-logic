import os
import json
import math

AB_LOG_PATH = "ab_log.json"
# Write next to the project (was a hardcoded machine-specific path that broke on any other
# machine and leaked a private local directory into the repo).
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration_report.md")

def pearson_r(x, y):
    n = len(x)
    if n < 2:
        return 0.0
    sum_x = sum(x)
    sum_y = sum(y)
    sum_x_sq = sum(xi ** 2 for xi in x)
    sum_y_sq = sum(yi ** 2 for yi in y)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))
    
    numerator = n * sum_xy - sum_x * sum_y
    denominator = math.sqrt((n * sum_x_sq - sum_x ** 2) * (n * sum_y_sq - sum_y ** 2))
    if denominator == 0:
        return 0.0
    return numerator / denominator

def main():
    if not os.path.exists(AB_LOG_PATH):
        print(f"[calibration_report] Error: No {AB_LOG_PATH} found.")
        return

    with open(AB_LOG_PATH, encoding="utf-8") as f:
        ab_log = json.load(f)

    # Filter videos with performance actuals
    valid_videos = []
    for video_id, info in ab_log.items():
        views_24h = info.get("views_first_24h")
        # fallback to total views if 24h views not yet collected
        views = views_24h if views_24h is not None else info.get("views")
        
        # Check if actual stats exist
        if views is not None or info.get("stayed_to_watch") is not None or info.get("avd") is not None:
            valid_videos.append({
                "id": video_id,
                "title": info.get("title", ""),
                "cluster": info.get("cluster", ""),
                "subcluster": info.get("subcluster", ""),
                "hook_type": info.get("hook_type", ""),
                "predicted_views_score": info.get("predicted_views_score", 0.0),
                "retention_prediction": info.get("retention_prediction", 0.0),
                "viewer_identity_score": info.get("viewer_identity_score", 0.0),
                "actual_views": views,
                "actual_retention": info.get("stayed_to_watch"), # Choose to watch %
                "actual_avd": info.get("avd"),
                "returning_viewers": info.get("returning_viewers"),
                "comments_per_1000_views": info.get("comments_per_1000_views"),
                "likes_per_1000_views": info.get("likes_per_1000_views")
            })

    if not valid_videos:
        print("[calibration_report] No videos with actual performance data found.")
        # Create blank report
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            f.write("# Calibration Report\n\nNo actual performance data collected yet. Please run `analytics_poll.py` or import YouTube Studio CSV metrics to populate actuals.\n")
        return

    # 1. predicted_views_score vs actual views
    pred_views = [v["predicted_views_score"] for v in valid_videos if v["actual_views"] is not None]
    act_views = [v["actual_views"] for v in valid_videos if v["actual_views"] is not None]
    views_r = pearson_r(pred_views, act_views) if len(pred_views) >= 2 else 0.0

    # 2. retention_prediction vs actual retention (stayed_to_watch)
    pred_ret = [v["retention_prediction"] for v in valid_videos if v["actual_retention"] is not None]
    act_ret = [v["actual_retention"] for v in valid_videos if v["actual_retention"] is not None]
    ret_r = pearson_r(pred_ret, act_ret) if len(pred_ret) >= 2 else 0.0
    ret_mae = sum(abs(p - a) for p, a in zip(pred_ret, act_ret)) / len(pred_ret) if pred_ret else 0.0

    # 3. viewer_identity_score vs returning_viewers / engagement rates
    vis_data = [v["viewer_identity_score"] for v in valid_videos if v["returning_viewers"] is not None]
    rv_data = [v["returning_viewers"] for v in valid_videos if v["returning_viewers"] is not None]
    vis_rv_r = pearson_r(vis_data, rv_data) if len(vis_data) >= 2 else 0.0

    vis_comm = [v["viewer_identity_score"] for v in valid_videos if v["comments_per_1000_views"] is not None]
    comm_rates = [v["comments_per_1000_views"] for v in valid_videos if v["comments_per_1000_views"] is not None]
    vis_comm_r = pearson_r(vis_comm, comm_rates) if len(vis_comm) >= 2 else 0.0

    vis_like = [v["viewer_identity_score"] for v in valid_videos if v["likes_per_1000_views"] is not None]
    like_rates = [v["likes_per_1000_views"] for v in valid_videos if v["likes_per_1000_views"] is not None]
    vis_like_r = pearson_r(vis_like, like_rates) if len(vis_like) >= 2 else 0.0

    # Build report content
    lines = []
    lines.append("# Calibration Phase Report — Recommendation Engine Accuracy")
    lines.append("")
    lines.append("> [!NOTE]")
    lines.append("  This report evaluates the accuracy of the recommendation engine scoring mechanisms against actual performance data.")
    lines.append("")
    
    lines.append("## Summary Statistics")
    lines.append("")
    lines.append(f"- **Total Videos with Performance Data:** {len(valid_videos)}")
    lines.append(f"- **Views Score vs. Actual Views Correlation (Pearson $r$):** {views_r:.2f} (Target: >0.60)")
    lines.append(f"- **Retention Prediction vs. Actual retention Correlation (Pearson $r$):** {ret_r:.2f} (Target: >0.60)")
    lines.append(f"- **Retention Prediction Mean Absolute Error (MAE):** {ret_mae:.1f}%")
    lines.append("")

    lines.append("## Audience Loyalty & Brand Identity Calibration")
    lines.append("")
    lines.append("Examines how the `viewer_identity_score` correlates with actual returning viewer counts and engagement rates:")
    lines.append(f"- **Identity Score vs. Returning Viewers Correlation ($r$):** {vis_rv_r:.2f}")
    lines.append(f"- **Identity Score vs. Comments Rate Correlation ($r$):** {vis_comm_r:.2f}")
    lines.append(f"- **Identity Score vs. Likes Rate Correlation ($r$):** {vis_like_r:.2f}")
    lines.append("")

    lines.append("## Video-by-Video Comparison")
    lines.append("")
    lines.append("| Title | Cluster | Predicted Views | Actual Views | Predicted Retention | Actual Retention | Viewer Identity | Returning Viewers | Comments/1k | Likes/1k |")
    lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for v in valid_videos:
        title_trunc = v["title"][:40] + "..." if len(v["title"]) > 40 else v["title"]
        lines.append(f"| {title_trunc} | {v['cluster']} | {v['predicted_views_score']:.1f} | {v['actual_views'] if v['actual_views'] is not None else '-'} | {v['retention_prediction']:.1f} | {v['actual_retention'] if v['actual_retention'] is not None else '-'}% | {v['viewer_identity_score']:.1f} | {v['returning_viewers'] if v['returning_viewers'] is not None else '-'} | {v['comments_per_1000_views'] if v['comments_per_1000_views'] is not None else '-'} | {v['likes_per_1000_views'] if v['likes_per_1000_views'] is not None else '-'} |")
    lines.append("")

    lines.append("## Category Calibration Analysis")
    lines.append("")
    cluster_stats = {}
    for v in valid_videos:
        if not v["cluster"]:
            continue
        c = v["cluster"]
        if c not in cluster_stats:
            cluster_stats[c] = {"views": [], "retention": [], "returning": [], "comments": [], "likes": []}
        if v["actual_views"] is not None:
            cluster_stats[c]["views"].append(v["actual_views"])
        if v["actual_retention"] is not None:
            cluster_stats[c]["retention"].append(v["actual_retention"])
        if v["returning_viewers"] is not None:
            cluster_stats[c]["returning"].append(v["returning_viewers"])
        if v["comments_per_1000_views"] is not None:
            cluster_stats[c]["comments"].append(v["comments_per_1000_views"])
        if v["likes_per_1000_views"] is not None:
            cluster_stats[c]["likes"].append(v["likes_per_1000_views"])

    lines.append("| Cluster | Count | Average Views (24h) | Average Retention % | Avg Returning Viewers | Avg Comments/1k | Avg Likes/1k |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
    for c, stats in cluster_stats.items():
        avg_v = sum(stats["views"]) / len(stats["views"]) if stats["views"] else 0.0
        avg_r = sum(stats["retention"]) / len(stats["retention"]) if stats["retention"] else 0.0
        avg_rv = sum(stats["returning"]) / len(stats["returning"]) if stats["returning"] else 0.0
        avg_cm = sum(stats["comments"]) / len(stats["comments"]) if stats["comments"] else 0.0
        avg_lk = sum(stats["likes"]) / len(stats["likes"]) if stats["likes"] else 0.0
        lines.append(f"| {c} | {len(stats['views'])} | {avg_v:.0f} | {avg_r:.1f}% | {avg_rv:.1f} | {avg_cm:.2f} | {avg_lk:.2f} |")

    # Write report
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        
    print(f"[calibration_report] Calibration report written to {REPORT_PATH}")

if __name__ == "__main__":
    main()
