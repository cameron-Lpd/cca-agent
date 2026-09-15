"""Tracks which webinar slugs have already been processed."""

import json
from pathlib import Path

STATE_FILE = Path(__file__).parent / "webinar_state.json"


def load_seen() -> set[str]:
    if not STATE_FILE.exists():
        return set()
    try:
        data = json.loads(STATE_FILE.read_text())
        return set(data.get("seen_slugs", []))
    except (json.JSONDecodeError, OSError):
        print("[State] Warning: state file corrupted or unreadable — starting fresh.")
        return set()


def save_seen(seen: set[str]) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"seen_slugs": sorted(seen)}, indent=2))
    tmp.replace(STATE_FILE)
