"""
Saves approved drafts to the correct OneDrive folder.

Path resolution:
  Marketing/Clients/{client_folder}/{webinar_folder}/
    ad_campaign.md
    dm_sequence.md

Client folder: fuzzy-matched against all companies involved in the webinar.
Webinar folder: fuzzy-matched against the webinar title.
"""

import re
from difflib import SequenceMatcher
from pathlib import Path

import config
from scraper import WebinarDetail


_SIMILARITY_THRESHOLD = 0.55  # minimum ratio for a fuzzy match


def has_existing_campaign(listing_title: str, companies: list[str]) -> bool:
    """
    Returns True if an ad_campaign.md already exists in the OneDrive folder
    matching this webinar. Used to skip webinars that are already covered.
    """
    clients_root = config.CLIENTS_PATH
    if not clients_root.exists():
        return False
    client_folder = _find_client_folder(clients_root, companies)
    if client_folder is None:
        return False
    webinar_folder = _find_webinar_folder(client_folder, listing_title)
    if webinar_folder is None:
        return False
    exists = (webinar_folder / "ad_campaign.md").exists()
    if exists:
        print(f"[OneDrive] Campaign already exists: {webinar_folder / 'ad_campaign.md'}")
    return exists


def save_drafts(
    ad_campaign: str,
    dm_sequence: str,
    detail: WebinarDetail,
) -> Path:
    """
    Locate the correct OneDrive folder and write both draft files.
    Returns the folder path where files were saved.
    Raises FileNotFoundError if no matching client or webinar folder is found.
    """
    clients_root = config.CLIENTS_PATH
    if not clients_root.exists():
        raise FileNotFoundError(f"Clients folder not found: {clients_root}")

    client_folder = _find_client_folder(clients_root, detail.all_clients)
    if client_folder is None:
        raise FileNotFoundError(
            f"No OneDrive client folder matched any of: {detail.all_clients}"
        )

    webinar_folder = _find_webinar_folder(client_folder, detail.title)
    if webinar_folder is None:
        raise FileNotFoundError(
            f"No webinar folder in '{client_folder.name}' matched: {detail.title}"
        )

    _write(webinar_folder / "ad_campaign.md", ad_campaign)
    _write(webinar_folder / "dm_sequence.md", dm_sequence)

    print(f"[OneDrive] Saved to: {webinar_folder}")
    return webinar_folder


# ── Folder resolution ─────────────────────────────────────────────────────────

def _find_client_folder(clients_root: Path, companies: list[str]) -> Path | None:
    """Return the subfolder of clients_root that best matches any company name."""
    candidates = [p for p in clients_root.iterdir() if p.is_dir()]
    best_path, best_score = None, 0.0

    for company in companies:
        for folder in candidates:
            score = _similarity(_normalise(company), _normalise(folder.name))
            if score > best_score:
                best_score = score
                best_path = folder

    if best_score >= _SIMILARITY_THRESHOLD:
        print(f"[OneDrive] Client folder matched: '{best_path.name}' (score {best_score:.2f})")
        return best_path

    print(f"[OneDrive] No client folder matched (best score {best_score:.2f}).")
    return None


def _find_webinar_folder(client_folder: Path, webinar_title: str) -> Path | None:
    """Return the subfolder of client_folder that best matches the webinar title."""
    candidates = [p for p in client_folder.iterdir() if p.is_dir()]
    best_path, best_score = None, 0.0
    norm_title = _normalise(webinar_title)

    for folder in candidates:
        score = _similarity(norm_title, _normalise(folder.name))
        if score > best_score:
            best_score = score
            best_path = folder

    if best_score >= _SIMILARITY_THRESHOLD:
        print(f"[OneDrive] Webinar folder matched: '{best_path.name}' (score {best_score:.2f})")
        return best_path

    print(f"[OneDrive] No webinar folder matched '{webinar_title}' (best score {best_score:.2f}).")
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    """Lowercase, strip punctuation and extra whitespace for comparison."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    print(f"[OneDrive] Written: {path.name}")
