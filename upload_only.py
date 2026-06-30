"""
upload_only.py - Uploads all completed drafts from the drafts/ directory immediately.
Skips generation, topic selection, script creation, TTS, visual search, and rendering.
Processes uploads in parallel with concurrency locks for shared JSON databases.
"""

import os
import sys
import json
import argparse
import datetime as dt
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import upload
import boost
import winner_memory

# Concurrency lock to protect writes to shared JSON databases (channel_index, ab_log, winner_memory)
db_lock = threading.Lock()

# Logging helper
def log(msg: str):
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    sys.stdout.flush()
    try:
        with open("pipeline_log.txt", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def compute_publish_slots(cfg: dict, n: int) -> list:
    """Build the next n publish datetimes from config 'publish_slots'
    rolling into following days as needed. Returns local datetimes, soonest first."""
    slots = cfg.get("publish_slots")
    if not slots:
        return []
    now = dt.datetime.now()
    candidates = []
    for day in range(8):
        for s in slots:
            h, m = map(int, str(s).split(":"))
            t = (now + dt.timedelta(days=day)).replace(hour=h, minute=m, second=0, microsecond=0)
            if t > now + dt.timedelta(minutes=3):
                candidates.append(t)
    candidates.sort()
    return candidates[:n]

def _to_utc_iso(local_dt) -> str:
    return local_dt.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def has_upload_marker(workdir: str) -> bool:
    """Check if the draft has already been uploaded."""
    if os.path.exists(os.path.join(workdir, "uploaded.txt")):
        return True
    if os.path.exists(os.path.join(workdir, ".uploaded")):
        return True
    meta_path = os.path.join(workdir, "meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
                if meta.get("uploaded") is True or "uploaded_url" in meta:
                    return True
        except Exception:
            pass
    return False

def mark_as_uploaded(workdir: str, url: str, publish_at: str | None):
    """Mark the draft as uploaded both via a file and in its meta.json."""
    timestamp = dt.datetime.now().isoformat()
    marker_path = os.path.join(workdir, "uploaded.txt")
    try:
        with open(marker_path, "w", encoding="utf-8") as f:
            f.write(f"Uploaded URL: {url}\n")
            f.write(f"Timestamp: {timestamp}\n")
            f.write(f"Publish At: {publish_at}\n")
    except Exception as e:
        log(f"Failed to write marker file in {workdir}: {e}")

    meta_path = os.path.join(workdir, "meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            meta["uploaded"] = True
            meta["uploaded_url"] = url
            meta["uploaded_at"] = timestamp
            if publish_at:
                meta["publish_at"] = publish_at
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            log(f"Failed to update meta.json in {workdir}: {e}")

def upload_single_draft(video_path: str, workdir: str, meta: dict, publish_at: str | None, dry_run: bool) -> str:
    """Uploads a single draft video and updates metadata / channel indices."""
    title = meta.get("title", "Untitled Short")
    description = meta.get("description", "")
    hashtags = meta.get("hashtags", [])
    tags = meta.get("tags", [])
    topic = meta.get("topic", "")

    if dry_run:
        log(f"[DRY-RUN] Would upload {video_path} | Title: {title} | Publish At: {publish_at}")
        return "https://youtube.com/watch?v=dryrun"

    # Step 1: Upload
    log(f"Starting upload for {video_path}...")
    url = upload.upload(video_path, title, description, hashtags, publish_at=publish_at, meta_tags=tags)
    log(f"Uploaded: {url}" + (f" (publishes {publish_at})" if publish_at else ""))
    
    video_id = url.rsplit("/", 1)[-1]

    # Step 2: Apply Thumbnail if cover.jpg exists
    try:
        cover = os.path.join(workdir, "cover.jpg")
        if os.path.exists(cover):
            upload.set_thumbnail(video_id, cover)
            log(f"Thumbnail applied for {video_id}")
    except Exception as e:
        log(f"Thumbnail application failed (non-fatal) for {video_id}: {e}")

    # Step 3: Record Upload in channel index (protected by lock)
    src = "pool"
    with db_lock:
        try:
            n = boost.record_upload(video_id, title, topic, source=src, metadata=meta)
            log(f"Recorded upload #{n} in channel index")
        except Exception as e:
            log(f"Failed to record upload in channel index: {e}")

    # Step 4: Localization (non-fatal)
    try:
        boost.localize(video_id, title, description)
        log(f"Localized {video_id} to ES/PT")
    except Exception as e:
        log(f"Localization failed (non-fatal) for {video_id}: {e}")

    # Step 5: Self-like (non-fatal)
    try:
        upload.post_like(video_id)
        log(f"Self-liked {video_id}")
    except Exception as e:
        log(f"Self-like failed (non-fatal) for {video_id}: {e}")

    # Step 6: First comment (if public immediately)
    if meta.get("first_comment") and not publish_at:
        try:
            upload.post_comment(video_id, meta["first_comment"])
            log(f"Seeded first comment for {video_id}: {meta['first_comment']}")
        except Exception as e:
            log(f"First comment failed (non-fatal) for {video_id}: {e}")

    # Step 7: Update Hook Library (protected by lock)
    try:
        hook_text = ""
        script_text = meta.get("script", "")
        if script_text:
            first_sentence = script_text.replace("\n", ". ").split(". ")[0].strip()
            hook_text = first_sentence + ("." if not first_sentence.endswith((".", "?", "!")) else "")
        
        with db_lock:
            winner_memory.update_hook_library(
                title=title,
                hook_text=hook_text,
                hook_type=meta.get("hook_type", "explainer"),
                hook_structure=meta.get("hook_structure", ""),
                first_frame_description=meta.get("first_frame_description", ""),
                visual_thesis=meta.get("visual_thesis", "")
            )
            log(f"Updated hook library for {video_id}")
    except Exception as e:
        log(f"Hook library update failed (non-fatal) for {video_id}: {e}")

    # Step 8: Update A/B test log (protected by lock)
    try:
        with db_lock:
            ab_path = "ab_log.json"
            ab = {}
            if os.path.exists(ab_path):
                with open(ab_path) as f:
                    ab = json.load(f)
            taxonomy = meta.get("taxonomy", "")
            subcluster = taxonomy.split("/")[1] if "/" in taxonomy else ""
            ab[video_id] = {
                "variant": meta.get("variant", "A"),
                "title": title,
                "date": dt.date.today().isoformat(),
                "publish_at": publish_at,
                "cluster": meta.get("cluster"),
                "topic": topic,
                "subcluster": subcluster,
                "hook_type": meta.get("hook_type", ""),
                "predicted_views_score": meta.get("predicted_views_score", 0.0),
                "retention_prediction": meta.get("retention_prediction", 0.0),
                "first_frame_score": meta.get("first_frame_score", 0.0),
                "viewer_identity_score": meta.get("viewer_identity_score", 0.0),
                "visual_thesis": meta.get("visual_thesis", ""),
                "first_frame_description": meta.get("first_frame_description", "")
            }
            with open(ab_path, "w") as f:
                json.dump(ab, f, indent=2)
            log(f"Recorded variant data in ab_log.json for {video_id}")
    except Exception as e:
        log(f"ab_log write skipped (non-fatal) for {video_id}: {e}")

    # Step 9: Write markers
    mark_as_uploaded(workdir, url, publish_at)

    return url

def main():
    parser = argparse.ArgumentParser(description="Upload completed drafts directly to YouTube.")
    parser.add_argument("--immediate", action="store_true", help="Upload all videos as public immediately (do not schedule).")
    parser.add_argument("--max-workers", type=int, default=3, help="Maximum concurrent uploads (default: 3).")
    parser.add_argument("--dry-run", action="store_true", help="Do not perform actual uploads; just log what would be done.")
    args = parser.parse_args()

    # Load configuration
    cfg = {}
    if os.path.exists("config.json"):
        try:
            with open("config.json") as f:
                cfg = json.load(f)
        except Exception as e:
            log(f"Error loading config.json: {e}")

    # Check OAuth token first (triggers authentication browser if not set or invalid)
    if not args.dry_run:
        log("Validating/refreshing YouTube OAuth credentials...")
        try:
            upload._service()
            log("OAuth token is active and valid.")
        except Exception as e:
            log(f"OAuth validation failed: {e}")
            log("Please make sure yt_token.pickle exists or run in interactive terminal to authorize.")
            sys.exit(1)

    log("Scanning drafts/ directory recursively...")
    all_drafts = []
    already_uploaded_count = 0

    if not os.path.exists("drafts"):
        log("No drafts/ directory found!")
        sys.exit(0)

    for root, dirs, files in os.walk("drafts"):
        for file in files:
            if file == "short.mp4":
                video_path = os.path.join(root, file)
                workdir = root
                
                # Check for upload marker
                if has_upload_marker(workdir):
                    already_uploaded_count += 1
                    continue

                # Load metadata
                meta = {}
                meta_path = os.path.join(workdir, "meta.json")
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, encoding="utf-8") as f:
                            meta = json.load(f)
                    except Exception as e:
                        log(f"Warning: Could not read metadata in {workdir}: {e}")
                
                all_drafts.append({
                    "video_path": video_path,
                    "workdir": workdir,
                    "meta": meta,
                    "score": float(meta.get("predicted_views_score", 0))
                })

    total_drafts_found = len(all_drafts) + already_uploaded_count
    log(f"Scan complete. Found {total_drafts_found} drafts total.")
    log(f"  - {already_uploaded_count} are already uploaded (skipped)")
    log(f"  - {len(all_drafts)} are pending upload")

    if not all_drafts:
        log("No pending drafts to upload.")
        print_summary(total_drafts_found, 0, 0, already_uploaded_count)
        sys.exit(0)

    # Sort drafts by predicted_views_score descending to publish best first
    all_drafts.sort(key=lambda x: x["score"], reverse=True)

    # Assign scheduling slots if not --immediate
    publish_at_slots = []
    if not args.immediate:
        log("Computing scheduling slots...")
        slot_times = compute_publish_slots(cfg, len(all_drafts) - 1)
        for i in range(len(all_drafts)):
            if i == 0:
                publish_at_slots.append(None) # First video published public immediately
            else:
                if i - 1 < len(slot_times):
                    publish_at_slots.append(_to_utc_iso(slot_times[i - 1]))
                else:
                    # Fallback if we run out of slots: schedule next day or incremental offset
                    last_slot = slot_times[-1] if slot_times else dt.datetime.now()
                    extra_delay = dt.timedelta(hours=(i - len(slot_times)) * 2)
                    publish_at_slots.append(_to_utc_iso(last_slot + extra_delay))
    else:
        log("Uploading all videos as public immediately (no scheduling slots).")
        publish_at_slots = [None] * len(all_drafts)

    # Process uploads in parallel
    succeeded_count = 0
    failed_count = 0
    futures = {}

    log(f"Starting parallel upload queue using {args.max_workers} worker threads...")
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        for idx, draft in enumerate(all_drafts):
            publish_at = publish_at_slots[idx]
            future = executor.submit(
                upload_single_draft, 
                draft["video_path"], 
                draft["workdir"], 
                draft["meta"], 
                publish_at, 
                args.dry_run
            )
            futures[future] = draft["workdir"]

        for future in as_completed(futures):
            workdir = futures[future]
            try:
                url = future.result()
                succeeded_count += 1
                log(f"SUCCESS: {workdir} uploaded successfully -> {url}")
            except Exception as e:
                failed_count += 1
                log(f"FAILED: {workdir} upload failed:")
                log(traceback.format_exc())

    print_summary(total_drafts_found, succeeded_count, failed_count, already_uploaded_count)

def print_summary(total, succeeded, failed, already):
    print("\n" + "="*40)
    print("           UPLOAD RUN SUMMARY")
    print("="*40)
    print(f"* Total drafts found: {total}")
    print(f"* Successfully uploaded: {succeeded}")
    print(f"* Failed uploads: {failed}")
    print(f"* Already uploaded: {already}")
    print("="*40 + "\n")
    sys.stdout.flush()

if __name__ == "__main__":
    main()
