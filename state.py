"""
Tracks which webinar slugs and LinkedIn post URNs have already been processed.

State is persisted in the hub's Turso DB via /api/agent/state so it survives
Railway restarts. The local JSON file is a write-through cache and fallback
for local development or when the hub is unreachable.
"""

import json
import urllib.request
import urllib.error
from pathlib import Path

STATE_FILE = Path(__file__).parent / "webinar_state.json"


# ── Hub I/O ───────────────────────────────────────────────────────────────────

def _hub_url() -> str | None:
    try:
        import config
        return config.HUB_URL.rstrip("/") if config.HUB_URL else None
    except Exception:
        return None


def _hub_secret() -> str:
    try:
        import config
        return config.HUB_CRON_SECRET or ""
    except Exception:
        return ""


def _hub_get() -> dict:
    url = _hub_url()
    if not url:
        return {}
    try:
        req = urllib.request.Request(
            f"{url}/api/agent/state",
            headers={"Authorization": f"Bearer {_hub_secret()}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[State] Hub read failed ({e}) — using local cache.")
        return {}


def _hub_patch(patch: dict) -> None:
    url = _hub_url()
    if not url:
        return
    try:
        req = urllib.request.Request(
            f"{url}/api/agent/state",
            data=json.dumps(patch).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_hub_secret()}",
            },
            method="PATCH",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[State] Hub write failed ({e}) — state saved locally only.")


# ── Local cache ───────────────────────────────────────────────────────────────

def _load_local() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        print("[State] Warning: local state file corrupted — starting fresh.")
        return {}


def _save_local(data: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(STATE_FILE)


# ── Public API ────────────────────────────────────────────────────────────────

def load_seen() -> set[str]:
    """Load seen webinar slugs. Prefers hub, falls back to local file."""
    hub = _hub_get()
    if hub:
        slugs = hub.get("seen_slugs", [])
        # Sync hub state into local cache so offline fallback stays fresh
        local = _load_local()
        local["seen_slugs"] = slugs
        _save_local(local)
        return set(slugs)
    return set(_load_local().get("seen_slugs", []))


def save_seen(seen: set[str]) -> None:
    slugs = sorted(seen)
    local = _load_local()
    local["seen_slugs"] = slugs
    _save_local(local)
    _hub_patch({"seen_slugs": slugs})


def load_seen_li_urns() -> set[str]:
    """Load seen LinkedIn post URNs. Prefers hub, falls back to local file."""
    hub = _hub_get()
    if hub:
        urns = hub.get("seen_urns", [])
        local = _load_local()
        local["seen_li_urns"] = urns
        _save_local(local)
        return set(urns)
    return set(_load_local().get("seen_li_urns", []))


def save_seen_li_urns(urns: set[str]) -> None:
    recent = sorted(urns)[-50:]
    local = _load_local()
    local["seen_li_urns"] = recent
    _save_local(local)
    _hub_patch({"seen_urns": recent})
