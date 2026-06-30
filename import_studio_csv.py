import os
import json
import csv
import argparse
import sys
import re

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import analytics_poll

AB_LOG_PATH = "ab_log.json"

def clean_percentage(val: str) -> float | None:
    """Clean percentage string (e.g. '65.4%' or '65,4') into float."""
    if not val:
        return None
    val_clean = val.replace("%", "").replace(",", ".").strip()
    try:
        return float(val_clean)
    except ValueError:
        return None

def clean_duration(val: str) -> float | None:
    """Clean duration string (e.g. '0:18' or '18' or '18.2') into seconds float."""
    if not val:
        return None
    val = val.strip()
    if ":" in val:
        # Time format like mm:ss or hh:mm:ss
        parts = val.split(":")
        try:
            if len(parts) == 2:
                return float(parts[0]) * 60.0 + float(parts[1])
            elif len(parts) == 3:
                return float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
        except ValueError:
            return None
    try:
        return float(val.replace(",", "."))
    except ValueError:
        return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Path to the YouTube Studio export CSV file")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f"[import_studio_csv] Error: File not found: {args.csv}")
        return

    if not os.path.exists(AB_LOG_PATH):
        print(f"[import_studio_csv] Error: No {AB_LOG_PATH} found. Upload some videos first.")
        return

    with open(AB_LOG_PATH, encoding="utf-8") as f:
        ab_log = json.load(f)

    # Parse CSV
    updated_count = 0
    with open(args.csv, newline="", encoding="utf-8-sig") as f:
        # Read header and first few lines to find columns
        reader = csv.reader(f)
        header = next(reader)
        
        # Map headers
        id_col = -1
        viewed_col = -1
        duration_col = -1
        returning_col = -1

        for i, col in enumerate(header):
            col_l = col.lower()
            if "video id" in col_l or "videoid" in col_l or (col_l == "id"):
                id_col = i
            elif "viewed (%)" in col_l or "viewed vs" in col_l or "chose to watch" in col_l or "stayed" in col_l:
                viewed_col = i
            elif "duration" in col_l or "avd" in col_l or "watch time" in col_l:
                duration_col = i
            elif "returning viewers" in col_l or "returningviewers" in col_l:
                returning_col = i

        if id_col == -1:
            # Fallback to column index 0 if not found
            id_col = 0
            print("[import_studio_csv] WARNING: Could not find explicit Video ID column in header. Guessing first column.")

        print(f"[import_studio_csv] Column mapping: ID={header[id_col] if id_col < len(header) else '?'}, "
              f"Viewed={header[viewed_col] if viewed_col != -1 else 'None'}, "
              f"Duration={header[duration_col] if duration_col != -1 else 'None'}, "
              f"ReturningViewers={header[returning_col] if returning_col != -1 else 'None'}")

        for row in reader:
            if not row or len(row) <= id_col:
                continue
            
            raw_id = row[id_col].strip()
            # Extract video ID in case it's a URL (e.g., https://youtu.be/DCXzmEGsHU0)
            video_id = raw_id.rsplit("/", 1)[-1].split("?")[0].strip()
            if not video_id:
                continue

            if video_id in ab_log:
                info = ab_log[video_id]
                updated = False
                
                if viewed_col != -1 and viewed_col < len(row):
                    val = clean_percentage(row[viewed_col])
                    if val is not None:
                        info["stayed_to_watch"] = val
                        updated = True
                
                if duration_col != -1 and duration_col < len(row):
                    val = clean_duration(row[duration_col])
                    if val is not None:
                        info["avd"] = val
                        updated = True
                        
                if returning_col != -1 and returning_col < len(row):
                    val_str = row[returning_col].strip().replace(",", "").replace(".", "")
                    try:
                        info["returning_viewers"] = int(val_str)
                        updated = True
                    except ValueError:
                        pass
                
                if updated:
                    updated_count += 1
                    print(f"  - Updated stats for {info.get('title')[:30]}... Choose to watch: {info.get('stayed_to_watch') or '?'}%, AVD: {info.get('avd') or '?'}s, Returning Viewers: {info.get('returning_viewers') or '?'}")

    if updated_count > 0:
        with open(AB_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(ab_log, f, indent=2)
        print(f"[import_studio_csv] Successfully imported stats for {updated_count} videos.")
        # Trigger re-aggregation of analytics memory
        analytics_poll.aggregate_analytics(ab_log)
    else:
        print("[import_studio_csv] No matching videos updated. Check if the CSV corresponds to the videos in ab_log.json.")

if __name__ == "__main__":
    main()
