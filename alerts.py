"""
alerts.py - $0 notifications when a daily run finishes or something breaks.

Two channels, both free, pick whichever you set up in config.json:
  1) Email via Gmail SMTP  (needs a Gmail "App Password", not your normal password)
  2) A webhook URL         (Discord/Slack/ntfy - paste a webhook and it just posts)

Config keys (all optional - if none are set, alerts are silently skipped):
  "alert_email_to":     "you@gmail.com"          # where to send
  "alert_email_from":   "you@gmail.com"          # the Gmail that sends (same is fine)
  "alert_email_app_password": "abcd efgh ijkl mnop"   # Google App Password
  "alert_webhook_url":  "https://discord.com/api/webhooks/..."  # or ntfy/slack
  "alert_only_on_failure": true   # if true, only ping when something failed

Nothing here ever raises - a broken alert must never break the pipeline.
"""
import json
import smtplib
import ssl
import urllib.request
import urllib.error
from email.mime.text import MIMEText


def _send_email(cfg: dict, subject: str, body: str) -> bool:
    to = cfg.get("alert_email_to")
    sender = cfg.get("alert_email_from") or to
    app_pw = cfg.get("alert_email_app_password")
    if not (to and sender and app_pw):
        return False
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as s:
            s.login(sender, app_pw.replace(" ", ""))  # app passwords show with spaces
            s.sendmail(sender, [to], msg.as_string())
        return True
    except Exception as e:
        print(f"[alerts] email failed (non-fatal): {e}")
        return False


def _send_webhook(cfg: dict, subject: str, body: str) -> bool:
    url = cfg.get("alert_webhook_url")
    if not url:
        return False
    try:
        # Discord/Slack accept {"content": "..."}; ntfy accepts raw text. Send content
        # as JSON which Discord & Slack both read. A real User-Agent is REQUIRED - Discord
        # returns 403 Forbidden for requests with the default Python-urllib agent.
        text = f"**{subject}**\n{body}"
        # Discord caps content at 2000 chars
        if len(text) > 1900:
            text = text[:1900] + "\n...(truncated)"
        data = json.dumps({"content": text, "text": text}).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json",
                     "User-Agent": "Hidden Logic-Bot/1.0 (+https://youtube.com)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            code = resp.getcode()
            return 200 <= code < 300
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        print(f"[alerts] webhook failed (non-fatal): HTTP {e.code} {e.reason}. {detail}")
        return False
    except Exception as e:
        print(f"[alerts] webhook failed (non-fatal): {e}")
        return False


def notify(cfg: dict, subject: str, body: str, is_failure: bool = False):
    """Send a notification through whatever channels are configured. Never raises."""
    try:
        if cfg.get("alert_only_on_failure") and not is_failure:
            return
        sent_any = False
        sent_any = _send_email(cfg, subject, body) or sent_any
        sent_any = _send_webhook(cfg, subject, body) or sent_any
        if not sent_any and (cfg.get("alert_email_to") or cfg.get("alert_webhook_url")):
            print("[alerts] no alert channel succeeded")
    except Exception as e:
        print(f"[alerts] notify failed (non-fatal): {e}")


# ---------------------------------------------------------------- growth / viral
import os as _os
import json as _json
import datetime as _dt

_VELOCITY_FILE = "view_velocity.json"


def _load_velocity():
    if _os.path.exists(_VELOCITY_FILE):
        try:
            return _json.load(open(_VELOCITY_FILE, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_velocity(data):
    try:
        _json.dump(data, open(_VELOCITY_FILE, "w", encoding="utf-8"), indent=2)
    except Exception:
        pass


def check_viral(cfg: dict, log=print) -> list:
    """Detect videos growing UNUSUALLY FAST (not a fixed view count). Compares each
    recent video's current views to a snapshot from the previous run to get views/hour,
    then flags any whose rate is well above the channel's typical recent rate. Stores
    fresh snapshots for next time. Returns list of (title, views, rate) that fired.
    Non-fatal: returns [] on any error."""
    try:
        import upload, boost
        idx = boost._load(boost.INDEX_FILE, [])
        if not idx:
            return []
        recent = idx[-30:]                      # only watch the last ~30 videos
        ids = [v["video_id"] for v in recent if v.get("video_id")]
        stats = upload.video_stats(ids)
        now = _dt.datetime.now(_dt.timezone.utc)
        now_iso = now.isoformat()
        prev = _load_velocity()
        snapshot, rates, fired = {}, [], []

        for v in recent:
            vid = v.get("video_id")
            s = stats.get(vid, {})
            views = int(s.get("viewCount", 0)) if isinstance(s, dict) else 0
            snapshot[vid] = {"views": views, "t": now_iso, "title": v.get("title", "")}
            p = prev.get(vid)
            if not p:
                continue
            try:
                dt_hours = (now - _dt.datetime.fromisoformat(p["t"])).total_seconds() / 3600
            except Exception:
                continue
            if dt_hours < 0.5:                  # too soon to judge
                continue
            gained = views - p.get("views", 0)
            rate = gained / dt_hours            # views per hour since last run
            if rate > 0:
                rates.append(rate)
            snapshot[vid]["rate"] = rate

        _save_velocity(snapshot)
        if len(rates) < 3:
            return []                           # not enough data to know what's "normal"

        rates_sorted = sorted(rates)
        median = rates_sorted[len(rates_sorted) // 2]
        # "unusually fast" = both well above the channel's median rate AND meaningful in
        # absolute terms (so a jump from 1 to 10 views/hr on a dead channel doesn't fire)
        for vid, snap in snapshot.items():
            rate = snap.get("rate", 0)
            views = snap.get("views", 0)
            if rate >= max(median * 4, 40) and views >= 300:
                fired.append((snap.get("title", "?"), views, round(rate)))
        fired.sort(key=lambda x: -x[2])
        if fired:
            log(f"viral check: {len(fired)} video(s) growing fast (median {median:.0f}/hr)")
        return fired
    except Exception as e:
        log(f"viral check failed (non-fatal): {e}")
        return []


_COMMENTS_SEEN_FILE = "comments_seen.json"


def check_new_comments(cfg: dict, log=print) -> int:
    """Count NEW comments since last run (by comment id), so you know when there are
    replies to attend to. Returns the count of new comments. Non-fatal -> 0 on error."""
    try:
        import upload
        comments = upload.fetch_recent_comments(max_results=40)
        if not comments:
            return 0
        seen = set()
        if _os.path.exists(_COMMENTS_SEEN_FILE):
            try:
                seen = set(_json.load(open(_COMMENTS_SEEN_FILE, encoding="utf-8")))
            except Exception:
                seen = set()
        ids_now = []
        for c in comments:
            cid = c.get("id") or (c.get("author", "") + "|" + c.get("text", "")[:40])
            ids_now.append(cid)
        new_ids = [c for c in ids_now if c not in seen]
        # persist the union so we don't re-alert old ones
        try:
            _json.dump(sorted(set(ids_now) | seen)[-500:],
                       open(_COMMENTS_SEEN_FILE, "w", encoding="utf-8"))
        except Exception:
            pass
        return len(new_ids)
    except Exception as e:
        log(f"comment check failed (non-fatal): {e}")
        return 0
