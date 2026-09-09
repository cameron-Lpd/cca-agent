"""Tracks which webinar slugs have already been processed."""

import json
from pathlib import Path

STATE_FILE = Path(__file__).parent / "webinar_state.json"


def load_seen() -> set[str]:
    if not STATE_FILE.exists():
        return set()
    data = json.loads(STATE_FILE.read_text())
    return set(data.get("seen_slugs", []))


def save_seen(seen: set[str]) -> None:
    STATE_FILE.write_text(json.dumps({"seen_slugs": sorted(seen)}, indent=2))
