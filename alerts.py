"""
Remote alerts for unattended runs (POST_CYCLE_FIXES P1-4).

Banners only help if someone is at the screen. send_alert() additionally posts the message to a
remote endpoint, if one is configured in ~/2pac_logs/gui_settings.json:

    "alerts": {
        "webhook_url": "https://hooks.slack.com/services/...",   # Slack/Mattermost-style {"text": ...}
        "ntfy_url": "https://ntfy.sh/<private-topic>",            # plain-text POST (phone push via ntfy app)
        "min_interval_s": 600                                     # per-key rate limit
    }

Nothing is sent when no endpoint is configured. Sending happens on a daemon thread so the state
machine never blocks on the network. Failures are printed, never raised.
"""
import json
import socket
import threading
import time
import urllib.request
from pathlib import Path

SETTINGS = Path.home() / "2pac_logs" / "gui_settings.json"
_last_sent = {}
_lock = threading.Lock()


def _config():
    try:
        return json.loads(SETTINGS.read_text()).get("alerts", {}) or {}
    except Exception:
        return {}


def is_configured():
    cfg = _config()
    return bool(cfg.get("webhook_url") or cfg.get("ntfy_url"))


def _post(url, data, content_type):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": content_type}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def _send(cfg, text):
    host = socket.gethostname()
    full = f"[2PAC @ {host}] {text}"
    if cfg.get("webhook_url"):
        try:
            _post(cfg["webhook_url"], json.dumps({"text": full}).encode(), "application/json")
        except Exception as e:
            print(f"[alerts] webhook failed: {e}")
    if cfg.get("ntfy_url"):
        try:
            _post(cfg["ntfy_url"], full.encode(), "text/plain; charset=utf-8")
        except Exception as e:
            print(f"[alerts] ntfy failed: {e}")


def send_alert(text, key=None):
    """Send `text` to the configured endpoints. Same `key` is sent at most once per min_interval_s."""
    cfg = _config()
    if not (cfg.get("webhook_url") or cfg.get("ntfy_url")):
        return False
    key = key or text[:60]
    now = time.time()
    with _lock:
        if now - _last_sent.get(key, 0.0) < float(cfg.get("min_interval_s", 600)):
            return False
        _last_sent[key] = now
    threading.Thread(target=_send, args=(cfg, str(text)), daemon=True).start()
    return True
