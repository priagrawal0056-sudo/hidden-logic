"""
test_alert.py - fire a test notification to confirm your Discord/email is set up.
Run:  python test_alert.py
This does NOT make a video or use any quota - it just sends one test message through
whatever alert channel you configured in config.json.
"""
import json
import os
import sys


def main():
    # This file is a manual smoke-test CLI, not an automated unittest module.
    # Keep configuration checks and network side effects out of module import so
    # standard test discovery can safely import it.
    import alerts

    if not os.path.exists("config.json"):
        sys.exit("config.json not found - run this from the footy-shorts folder.")

    with open("config.json", encoding="utf-8") as config_file:
        cfg = json.load(config_file)

    # show what's configured (without printing secrets)
    has_webhook = bool(cfg.get("alert_webhook_url"))
    has_email = bool(cfg.get("alert_email_to") and cfg.get("alert_email_app_password"))
    print(f"Discord/webhook configured: {has_webhook}")
    print(f"Email configured:           {has_email}")
    if not (has_webhook or has_email):
        sys.exit("\nNo alert channel set in config.json. Add 'alert_webhook_url' (Discord) "
                 "or the alert_email_* keys, then run this again.")

    print("\nSending a test alert...")
    alerts.notify(
        cfg,
        "Hidden Logic test alert",
        "If you can read this, your alerts are working. "
        "You'll get a message like this after every run.",
        is_failure=True,   # force-send even if alert_only_on_failure is set
    )
    print("Done. Check Discord / your email now.")
    print("If nothing arrived, double-check the webhook URL or app password in config.json.")


if __name__ == "__main__":
    main()
