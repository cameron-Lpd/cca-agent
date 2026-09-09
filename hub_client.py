"""
HTTP client for the PD-Create hub.

Gate 1  — deliver_detection_to_hub(listing)   POST /api/webinar-detections
Gate 2  — deliver_to_hub(...)                 POST /api/campaign-package
"""

import json
import requests

import config
from scraper import WebinarListing, WebinarDetail
from date_mapper import ScheduledPost


# ── Gate 1: webinar detection ─────────────────────────────────────────────────

def deliver_detection_to_hub(listing: WebinarListing) -> str:
    """
    Notify the hub of a newly detected webinar (Gate 1).
    Returns the hub-assigned detection ID.
    Raises requests.HTTPError on failure.
    """
    payload = {
        "source_id": listing.slug,
        "title": listing.title,
        "date": listing.date,
        "primary_client": listing.primary_client,
        "url": listing.url,
        "source_agent": "CCA v1",
    }

    resp = requests.post(
        f"{config.HUB_URL.rstrip('/')}/api/webinar-detections",
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()

    data = resp.json()
    detection_id = data.get("detection", {}).get("id", "")
    status = data.get("status", "")
    print(f"[Hub Gate 1] Detection {status}. ID: {detection_id or '(none)'}")
    return detection_id


# ── Gate 2: campaign drafts ───────────────────────────────────────────────────

def deliver_to_hub(
    ad_campaign: str,
    dm_sequence: str,
    detail: WebinarDetail,
    post_schedule: list[ScheduledPost],
) -> list[str]:
    """
    POST the final draft package to the hub (Gate 2).
    Returns list of hub-assigned campaign IDs.
    Raises requests.HTTPError on failure.
    """
    if not config.HUB_URL:
        print("[Hub] HUB_URL not set — printing payload to console instead.")
        _print_payload(ad_campaign, dm_sequence, detail, post_schedule)
        return ["local-preview"]

    source_id = detail.source_url.rstrip("/").split("/")[-1]  # slug from URL

    payload = {
        "source_id": source_id,
        "source_agent": "CCA v1",
        "post_schedule": [p.to_dict() for p in post_schedule],
        "ad_campaign": {
            "name": f"{detail.title} — Ad Campaign",
            "caption": ad_campaign,
            "destination_url": detail.registration_url or detail.source_url,
        },
        "dm_sequence": {
            "name": f"{detail.title} — DM Sequence",
            "messages": [{"body": dm_sequence, "delay_days": 0}],
        },
    }

    headers = {}
    if config.HUB_SECRET:
        headers["X-PD-Create-Secret"] = config.HUB_SECRET

    resp = requests.post(
        f"{config.HUB_URL.rstrip('/')}/api/campaign-package",
        json=payload,
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()

    campaigns = resp.json().get("campaigns", [])
    ids = [c.get("id", "") for c in campaigns]
    print(f"[Hub Gate 2] Delivered {len(ids)} campaign(s). IDs: {ids}")
    return ids


def _print_payload(
    ad_campaign: str,
    dm_sequence: str,
    detail: WebinarDetail,
    post_schedule: list[ScheduledPost],
) -> None:
    preview = {
        "source_id": detail.source_url.rstrip("/").split("/")[-1],
        "webinar": detail.title,
        "primary_client": detail.primary_client,
        "campaign_posts": len(post_schedule),
        "registration_url": detail.registration_url,
    }
    print(json.dumps(preview, indent=2))
    print("\n--- AD CAMPAIGN (first 500 chars) ---")
    print(ad_campaign[:500])
    print("\n--- DM SEQUENCE (first 500 chars) ---")
    print(dm_sequence[:500])
