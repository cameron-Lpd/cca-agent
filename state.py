"""Tracks which webinar slugs and LinkedIn post URNs have already been processed."""

import json
from pathlib import Path

STATE_FILE = Path(__file__).parent / "webinar_state.json"


def _load() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        print("[State] Warning: state file corrupted or unreadable — starting fresh.")
        return {}


def _save(data: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(STATE_FILE)


def load_seen() -> set[str]:
    return set(_load().get("seen_slugs", []))


def save_seen(seen: set[str]) -> None:
    data = _load()
    data["seen_slugs"] = sorted(seen)
    _save(data)


def load_seen_li_urns() -> set[str]:
    return set(_load().get("seen_li_urns", []))


def save_seen_li_urns(urns: set[str]) -> None:
    data = _load()
    # Keep only the 50 most recent URNs to avoid unbounded growth
    data["seen_li_urns"] = sorted(urns)[-50:]
    _save(data)
