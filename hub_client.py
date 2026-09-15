"""
HTTP client for the PD-Create hub.

Gate 1  — deliver_detection_to_hub(listing)   POST /api/webinar-detections
Gate 2  — deliver_to_hub(...)                 POST /api/campaign-package
"""

import json
import re
import requests

import config
from scraper import WebinarListing, WebinarDetail
from date_mapper import ScheduledPost
from document_generator import generate_campaign_docx, generate_dm_docx, to_base64


def _parse_dm_messages(dm_text: str) -> list[dict]:
    """Split a DM sequence text into individual message objects with delay days."""
    DELAY_DAYS = [0, 3, 7, 14, 21]
    blocks = re.split(r'(?m)(?=^\s*MESSAGE\s+\d+\b)', dm_text.strip())
    messages = []
    for i, block in enumerate(blocks):
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        header = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        label_match = re.match(r'MESSAGE\s+\d+\s*[-–]\s*(.*)', header)
        label = label_match.group(1).strip() if label_match else header
        messages.append({
            "body": body,
            "delay_days": DELAY_DAYS[i] if i < len(DELAY_DAYS) else i * 3,
            "label": label,
        })
    if not messages:
        messages = [{"body": dm_text, "delay_days": 0}]
    return messages


# ── Gate 1: webinar detection ─────────────────────────────────────────────────

def deliver_detection_to_hub(listing: WebinarListing) -> tuple[str, str, str]:
    """
    Notify the hub of a newly detected webinar (Gate 1).
    Returns (detection_id, hub_status, detection_status).
    hub_status: 'received' or 'already_received'
    detection_status: current status of the detection record in hub (e.g. 'AWAITING_REVIEW', 'REJECTED')
    """
    payload = {
        "source_id": listing.slug,
        "title": listing.title,
        "date": listing.date,
        "primary_client": listing.primary_client,
        "url": listing.url,
        "source_agent": "CCA v1",
        # Note: all_clients is only available in WebinarDetail (post deep-scrape), not at Gate 1
    }

    headers = {}
    if config.HUB_SECRET:
        headers["X-PD-Create-Secret"] = config.HUB_SECRET
    resp = requests.post(
        f"{config.HUB_URL.rstrip('/')}/api/webinar-detections",
        json=payload,
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()

    data = resp.json()
    detection_id = data.get("detection", {}).get("id", "")
    status = data.get("status", "")
    detection_status = data.get("detection", {}).get("status", "AWAITING_REVIEW")
    print(f"[Hub Gate 1] Detection {status}. ID: {detection_id or '(none)'}")
    return detection_id, status, detection_status


# ── Gate 2: campaign drafts ───────────────────────────────────────────────────

def deliver_to_hub(
    ad_campaign: str,
    dm_sequence: str,
    detail: WebinarDetail,
    post_schedule: list[ScheduledPost],
    source_id: str | None = None,
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

    if source_id is None:
        source_id = detail.source_url.rstrip("/").split("/")[-1]

    ad_name = f"{detail.title} — Ad Campaign"
    dm_name = f"{detail.title} — DM Sequence"

    print("[Hub Gate 2] Generating Word documents...")
    try:
        ad_docx = to_base64(generate_campaign_docx(ad_name, ad_campaign, detail))
        dm_docx = to_base64(generate_dm_docx(dm_name, dm_sequence, detail))
    except Exception as e:
        print(f"[Hub Gate 2] Warning: docx generation failed ({e}) — sending text only.")
        ad_docx = None
        dm_docx = None

    payload = {
        "source_id": source_id,
        "source_agent": "CCA v1",
        "post_schedule": [p.to_dict() for p in post_schedule],
        "ad_campaign": {
            "name": ad_name,
            "caption": ad_campaign,
            "destination_url": detail.registration_url or detail.source_url,
            **({"docx_base64": ad_docx} if ad_docx else {}),
        },
        "dm_sequence": {
            "name": dm_name,
            "messages": _parse_dm_messages(dm_sequence),
            **({"docx_base64": dm_docx} if dm_docx else {}),
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
