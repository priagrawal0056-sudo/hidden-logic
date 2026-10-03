"""
config_loader.py - one place to load config.json with environment-variable overlay.

Why this exists:
  Secrets (API keys, the Discord webhook) should NOT have to live in config.json in
  plaintext. This loader reads config.json (for non-secret settings) and then overlays
  any secret found in an environment variable, so you can keep keys OUT of the file.

Precedence (highest wins): environment variable > config.json value.

Recognized environment variables (set these in your OS / Task Scheduler instead of
putting them in config.json):
  HL_GEMINI_API_KEY        -> gemini_api_key
  HL_PEXELS_API_KEY        -> pexels_api_key
  HL_PIXABAY_API_KEY       -> pixabay_api_key
  HL_FOOTBALLDATA_API_KEY  -> footballdata_api_key
  HL_ALERT_WEBHOOK_URL     -> alert_webhook_url
  HL_ROLLOUT_ENABLED       -> rollout_enabled (boolean; default false)
  HL_PILOT_REVIEW_COMPLETE -> pilot_review_complete (boolean; default false)

Backwards compatible: if you keep your keys in config.json, nothing changes.
If both are set, the environment variable wins.
"""
import json
import os

CONFIG_FILE = "config.json"

# env var name -> config key
_SECRET_ENV_MAP = {
    "HL_GEMINI_API_KEY": "gemini_api_key",
    "HL_PEXELS_API_KEY": "pexels_api_key",
    "HL_PIXABAY_API_KEY": "pixabay_api_key",
    "HL_FOOTBALLDATA_API_KEY": "footballdata_api_key",
    "HL_ALERT_WEBHOOK_URL": "alert_webhook_url",
}

_BOOLEAN_ENV_MAP = {
    "HL_ROLLOUT_ENABLED": "rollout_enabled",
    "HL_PILOT_REVIEW_COMPLETE": "pilot_review_complete",
}

_SECRET_KEYS = set(_SECRET_ENV_MAP.values())


def load_config(path: str = CONFIG_FILE) -> dict:
    """Load config.json (if present) and overlay secrets from environment variables."""
    cfg = {}
    source = path
    if not os.path.exists(source) and os.path.basename(path) == CONFIG_FILE:
        # Hosted CI may inject all secrets through environment variables and intentionally
        # omit the ignored config.json. Use the committed non-secret template in that case.
        if os.path.exists("config.example.json"):
            source = "config.example.json"
    if os.path.exists(source):
        with open(source, encoding="utf-8") as f:
            cfg = json.load(f)
    for env_name, cfg_key in _SECRET_ENV_MAP.items():
        val = os.environ.get(env_name)
        if val:
            cfg[cfg_key] = val
    for env_name, cfg_key in _BOOLEAN_ENV_MAP.items():
        raw = os.environ.get(env_name)
        if raw is not None:
            cfg[cfg_key] = raw.strip().lower() in {"1", "true", "yes", "on"}
    # Missing rollout keys are opt-out; never infer publication permission from an old config.
    cfg.setdefault("rollout_enabled", False)
    cfg.setdefault("pilot_review_complete", False)
    return cfg


def redacted(cfg: dict) -> dict:
    """Return a copy safe for logging: secret values masked."""
    out = {}
    for k, v in cfg.items():
        if k in _SECRET_KEYS and v:
            s = str(v)
            out[k] = (s[:4] + "..." + s[-2:]) if len(s) > 6 else "***"
        else:
            out[k] = v
    return out


_WARNED_SECRETS = False


def warn_if_secrets_in_file(path: str = CONFIG_FILE) -> list:
    """Print a one-time warning if config.json still stores live-looking secrets in plaintext.
    Secrets should come from HL_* environment variables (see module docstring) and config.json
    should be git-ignored. Non-fatal: the pipeline still runs with in-file secrets. Returns the
    list of leaked keys."""
    global _WARNED_SECRETS
    try:
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return []
    leaked = []
    for k in _SECRET_KEYS:
        v = raw.get(k)
        if isinstance(v, str) and v and "PASTE_" not in v and "_HERE" not in v:
            leaked.append(k)
    if leaked and not _WARNED_SECRETS:
        _WARNED_SECRETS = True
        print("[config] SECURITY: live secrets are stored in config.json (" +
              ", ".join(sorted(set(leaked))) + "). Anyone who gets this folder gets these keys. "
              "Move them to HL_* environment variables and keep config.json git-ignored. "
              "If this folder was ever shared or zipped, ROTATE these keys.")
    return leaked
