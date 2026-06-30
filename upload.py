"""
upload.py - Uploads a finished Short to YouTube via the official Data API.
One-time setup: client_secret.json from Google Cloud Console (see README).
First run opens a browser to authorize; the token is then saved and reused.
"""
import os
import pickle
import random
import socket
import threading
import time

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]
TOKEN_FILE = "yt_token.pickle"
CLIENT_SECRET = "client_secret.json"

# Serialize token refresh/write so parallel upload workers can't interleave a pickle.dump and
# corrupt yt_token.pickle (which would force a manual browser re-auth and break "walk away").
_token_lock = threading.Lock()
_RETRIABLE_STATUS = {500, 502, 503, 504}
_QUOTA_REASONS = ("quotaExceeded", "uploadLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded")


class UploadQuotaError(RuntimeError):
    """Raised when YouTube refuses an upload because the daily quota / upload limit is hit, so
    the caller can stop the batch and defer the remaining videos to the next run."""


def _video_defaults():
    """categoryId + defaultLanguage, configurable via config.json ('category_id'/'default_language').
    Defaults: 27 (Education) / en, which suit the everyday-psychology niche."""
    try:
        import config_loader
        cfg = config_loader.load_config("config.json")
        return str(cfg.get("category_id", "27")), str(cfg.get("default_language", "en"))
    except Exception:
        return "27", "en"


def _service():
    with _token_lock:
        creds = None
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, "rb") as f:
                creds = pickle.load(f)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
                creds = flow.run_local_server(port=0)
            # atomic write (tmp + replace) so a torn/concurrent write can't corrupt the token
            tmp = TOKEN_FILE + ".tmp"
            with open(tmp, "wb") as f:
                pickle.dump(creds, f)
            os.replace(tmp, TOKEN_FILE)
    return build("youtube", "v3", credentials=creds)


def upload(video_path: str, title: str, description: str, tags: list[str],
           publish_at: str | None = None, meta_tags: list[str] | None = None) -> str:
    yt = _service()
    # visible hashtags go in the description; hidden Studio tags use the richer meta_tags
    # set if provided (broad-to-specific search categorization), else fall back to hashtags.
    hidden_tags = [t.lstrip("#") for t in (meta_tags if meta_tags else tags)]
    _cat_id, _lang = _video_defaults()
    body = {
        "snippet": {
            "title": title[:100],
            "description": description + "\n\n" + " ".join(tags),
            "tags": hidden_tags,
            "categoryId": _cat_id,        # configurable (default 27 = Education)
            "defaultLanguage": _lang,     # configurable (default en)
        },
        "status": {
            "privacyStatus": "private" if publish_at else "public",
            "selfDeclaredMadeForKids": False,
            **({"publishAt": publish_at} if publish_at else {}),
        },
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    retry = 0
    while response is None:
        try:
            _, response = request.next_chunk()
        except HttpError as e:
            status = getattr(getattr(e, "resp", None), "status", None)
            detail = str(e)
            # daily quota / upload-limit: not retriable here - tell the caller to defer the rest
            if status == 403 and any(r in detail for r in _QUOTA_REASONS):
                raise UploadQuotaError(
                    "YouTube upload quota / daily limit reached - defer remaining videos to the "
                    "next run. " + detail[:300])
            if status in _RETRIABLE_STATUS:
                retry += 1
                if retry > 5:
                    raise RuntimeError(f"Upload failed after {retry} retries (HTTP {status}): {detail[:300]}")
                time.sleep(min(2 ** retry + random.random(), 30))
                continue
            raise
        except (socket.error, OSError, ConnectionError) as e:
            # transient network blip: back off and retry rather than permanently failing the video
            retry += 1
            if retry > 5:
                raise RuntimeError(f"Upload failed after {retry} network retries: {e}")
            time.sleep(min(2 ** retry + random.random(), 30))
    return f"https://youtube.com/shorts/{response['id']}"


def post_comment(video_id: str, text: str):
    """Post the channel's first comment under a freshly published video."""
    yt = _service()
    yt.commentThreads().insert(
        part="snippet",
        body={"snippet": {"videoId": video_id, "topLevelComment":
              {"snippet": {"textOriginal": text}}}},
    ).execute()


def post_like(video_id: str):
    """Like the video from the channel's own account (sets a non-zero baseline)."""
    yt = _service()
    yt.videos().rate(id=video_id, rating="like").execute()


def video_stats(video_ids: list[str]) -> dict:
    """Return {video_id: view_count} for up to 50 ids."""
    yt = _service()
    resp = yt.videos().list(part="statistics", id=",".join(video_ids[:50])).execute()
    return {item["id"]: {"viewCount": int(item.get("statistics", {}).get("viewCount", 0)),
                         "likeCount": int(item.get("statistics", {}).get("likeCount", 0)),
                         "commentCount": int(item.get("statistics", {}).get("commentCount", 0))}
            for item in resp.get("items", [])}


def update_snippet(video_id: str, title: str, description: str):
    yt = _service()
    current = yt.videos().list(part="snippet", id=video_id).execute()["items"][0]["snippet"]
    current["title"] = title
    current["description"] = description
    yt.videos().update(part="snippet", body={"id": video_id, "snippet": current}).execute()


def set_localizations(video_id: str, localizations: dict):
    yt = _service()
    yt.videos().update(part="localizations",
                       body={"id": video_id, "localizations": localizations}).execute()


def fetch_recent_comments(max_results: int = 15) -> list[dict]:
    yt = _service()
    ch = yt.channels().list(part="id", mine=True).execute()["items"][0]["id"]
    resp = yt.commentThreads().list(part="snippet", allThreadsRelatedToChannelId=ch,
                                    maxResults=max_results, order="time").execute()
    raw = []
    vid_ids = set()
    for t in resp.get("items", []):
        top = t["snippet"]["topLevelComment"]["snippet"]
        if top.get("authorChannelId", {}).get("value") == ch:
            continue  # don't reply to ourselves
        vid = t["snippet"].get("videoId", "")
        vid_ids.add(vid)
        raw.append({"comment_id": t["snippet"]["topLevelComment"]["id"],
                    "text": top.get("textDisplay", ""),
                    "video_id": vid})
    # look up the ACTUAL title of each video the comments are on, so replies have the right
    # context (previously this stored the video ID as the "title", which is why replies
    # invented wrong context). One batched call for up to 50 ids.
    titles = {}
    ids = [v for v in vid_ids if v]
    if ids:
        try:
            vresp = yt.videos().list(part="snippet", id=",".join(ids[:50])).execute()
            for it in vresp.get("items", []):
                titles[it["id"]] = it["snippet"].get("title", "")
        except Exception:
            pass
    out = []
    for c in raw:
        out.append({"comment_id": c["comment_id"],
                    "text": c["text"],
                    "video_id": c["video_id"],
                    "video_title": titles.get(c["video_id"], "")})
    return out


def post_reply(comment_id: str, text: str):
    yt = _service()
    yt.comments().insert(part="snippet",
                         body={"snippet": {"parentId": comment_id,
                                           "textOriginal": text}}).execute()


# ---- PLAYLISTS: group videos into their franchise playlists automatically so the channel
# reads as a set of named shows (helps binge-watching and subscriber conversion). Playlist
# IDs are cached to disk so we don't re-list every run (saves quota).
_PLAYLIST_CACHE = "playlists.json"


def _load_playlist_cache() -> dict:
    if os.path.exists(_PLAYLIST_CACHE):
        try:
            import json
            with open(_PLAYLIST_CACHE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_playlist_cache(cache: dict):
    try:
        import json
        with open(_PLAYLIST_CACHE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def get_or_create_playlist(title: str, description: str = "") -> str | None:
    """Return the playlist ID for `title`, creating the playlist if it doesn't exist yet.
    Caches the mapping (title -> id) to disk. Returns None on failure (caller is non-fatal).
    Verifies a cached id still exists before trusting it (self-heals if a playlist was
    deleted)."""
    cache = _load_playlist_cache()
    yt = _service()
    # trust the cache, but verify the playlist still exists
    if title in cache:
        try:
            chk = yt.playlists().list(part="id", id=cache[title]).execute()
            if chk.get("items"):
                return cache[title]
        except Exception:
            pass  # fall through and re-resolve

    # look through the channel's existing playlists for a name match (in case it exists
    # but isn't cached, e.g. created by hand)
    try:
        page = None
        for _ in range(10):
            resp = yt.playlists().list(part="snippet", mine=True, maxResults=50,
                                       pageToken=page).execute()
            for it in resp.get("items", []):
                if it["snippet"]["title"].strip().lower() == title.strip().lower():
                    cache[title] = it["id"]
                    _save_playlist_cache(cache)
                    return it["id"]
            page = resp.get("nextPageToken")
            if not page:
                break
    except Exception:
        pass

    # create it
    try:
        body = {"snippet": {"title": title, "description": description},
                "status": {"privacyStatus": "public"}}
        created = yt.playlists().insert(part="snippet,status", body=body).execute()
        pid = created["id"]
        cache[title] = pid
        _save_playlist_cache(cache)
        return pid
    except Exception:
        return None


def _playlist_contains(yt, playlist_id: str, video_id: str) -> bool:
    """True if the video is already in the playlist (avoid duplicate adds)."""
    try:
        page = None
        for _ in range(20):
            resp = yt.playlistItems().list(part="contentDetails", playlistId=playlist_id,
                                           maxResults=50, pageToken=page).execute()
            for it in resp.get("items", []):
                if it.get("contentDetails", {}).get("videoId") == video_id:
                    return True
            page = resp.get("nextPageToken")
            if not page:
                break
    except Exception:
        pass
    return False


def add_to_playlist(video_id: str, playlist_title: str, playlist_desc: str = "") -> bool:
    """Add a video to a franchise playlist by NAME, creating the playlist if needed and
    skipping if the video is already in it. Fully non-fatal: returns True/False, never raises,
    so a playlist hiccup can't break the upload pipeline."""
    if not video_id or not playlist_title:
        return False
    try:
        pid = get_or_create_playlist(playlist_title, playlist_desc)
        if not pid:
            return False
        yt = _service()
        if _playlist_contains(yt, pid, video_id):
            return True  # already there, treat as success
        yt.playlistItems().insert(
            part="snippet",
            body={"snippet": {"playlistId": pid,
                              "resourceId": {"kind": "youtube#video", "videoId": video_id}}}
        ).execute()
        return True
    except Exception:
        return False


def list_uploads(max_results: int = 50) -> list[dict]:
    """Return recent uploads [{video_id, title, description, published}] from the channel itself."""
    yt = _service()
    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    playlist = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    resp = yt.playlistItems().list(part="snippet", playlistId=playlist,
                                   maxResults=max_results).execute()
    out = []
    for item in resp.get("items", []):
        s = item["snippet"]
        out.append({"video_id": s["resourceId"]["videoId"], "title": s["title"],
                    "description": s.get("description", ""),
                    "published": s.get("publishedAt", "")[:10]})
    return out


def set_thumbnail(video_id: str, image_path: str):
    """Set a custom thumbnail. Custom thumbnails require a VERIFIED YouTube channel
    (phone verification at youtube.com/verify). Raises with a clear reason on failure;
    the caller decides whether to treat it as fatal."""
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    yt = _service()
    try:
        yt.thumbnails().set(videoId=video_id,
                            media_body=MediaFileUpload(image_path)).execute()
    except HttpError as e:
        status = getattr(e.resp, "status", "?")
        detail = ""
        try:
            import json as _json
            err = _json.loads(e.content.decode("utf-8"))
            reason = err.get("error", {}).get("errors", [{}])[0].get("reason", "")
            msg = err.get("error", {}).get("message", "")
            detail = f" reason={reason!r} msg={msg!r}"
        except Exception:
            pass
        if str(status) == "403":
            raise RuntimeError(
                "YouTube refused the custom thumbnail (403). Two common causes: (1) for "
                "SHORTS specifically, YouTube restricts custom-thumbnail uploads via the API/"
                "desktop path - the thumbnail only shows in search/channel/suggestions anyway, "
                "NOT in the swipe feed, so this is low-impact and safe to ignore; (2) the "
                "channel isn't verified (youtube.com/verify with a phone number). If these are "
                "Shorts, (1) is the likely cause and not worth chasing."
                + detail) from e
        raise RuntimeError(f"Thumbnail upload failed (HTTP {status}).{detail}") from e


def _analytics():
    """YouTube Analytics service (read-only scope authorized earlier)."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
    return build("youtubeAnalytics", "v2", credentials=creds)


def video_retention(video_ids: list, days: int = 28) -> dict:
    """Average view percentage (0-100) per video over the trailing window.
    Single batched call using dimensions=video. {} on failure (non-fatal)."""
    import datetime as _dt
    if not video_ids:
        return {}
    try:
        ya = _analytics()
        end = _dt.date.today()
        start = end - _dt.timedelta(days=days)
        resp = ya.reports().query(
            ids="channel==MINE",
            startDate=start.isoformat(),
            endDate=end.isoformat(),
            metrics="averageViewPercentage",
            dimensions="video",
            filters="video==" + ",".join(video_ids[:200]),
            maxResults=200,
        ).execute()
        out = {}
        for row in resp.get("rows", []):
            out[row[0]] = float(row[1])  # video_id -> avg view %
        return out
    except Exception:
        return {}


def video_analytics(video_ids: list, days: int = 28) -> dict:
    """Average view duration (seconds) and average view percentage (0-100) per video.
    Single batched call using dimensions=video. Returns {video_id: {"avd": float, "retention": float}}."""
    import datetime as _dt
    if not video_ids:
        return {}
    try:
        ya = _analytics()
        end = _dt.date.today()
        start = end - _dt.timedelta(days=days)
        resp = ya.reports().query(
            ids="channel==MINE",
            startDate=start.isoformat(),
            endDate=end.isoformat(),
            metrics="averageViewDuration,averageViewPercentage",
            dimensions="video",
            filters="video==" + ",".join(video_ids[:200]),
            maxResults=200,
        ).execute()
        out = {}
        for row in resp.get("rows", []):
            out[row[0]] = {
                "avd": float(row[1]),
                "retention": float(row[2])
            }
        return out
    except Exception:
        return {}


def retention_curve(video_id: str, days: int = 28) -> list:
    """The 100-point audience-retention curve for ONE video. Returns list of
    (elapsed_ratio, watch_ratio) sorted by elapsed. [] on failure (non-fatal).
    One API call per video, so callers fetch this only for a few key videos."""
    import datetime as _dt
    try:
        ya = _analytics()
        end = _dt.date.today()
        start = end - _dt.timedelta(days=days)
        resp = ya.reports().query(
            ids="channel==MINE",
            startDate=start.isoformat(),
            endDate=end.isoformat(),
            metrics="audienceWatchRatio",
            dimensions="elapsedVideoTimeRatio",
            filters="video==" + video_id,
            sort="elapsedVideoTimeRatio",
            maxResults=200,
        ).execute()
        return [(float(r[0]), float(r[1])) for r in resp.get("rows", [])]
    except Exception:
        return []
