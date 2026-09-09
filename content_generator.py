"""
Content generation pipeline:
  1. Template  — slot scraped data into a base structure
  2. Draft ×3  — one draft per reference example
  3. Merge     — Claude collapses the 3 drafts into one superior final draft

Reference examples live in references/:
  references/campaign_1.md, campaign_2.md, campaign_3.md
  references/dm_1.md,       dm_2.md,       dm_3.md

Drop the 3 top-performing historical campaigns/DM sequences into those files.
The agent loads them automatically on each run.
"""

from pathlib import Path

import anthropic

import config
from scraper import WebinarDetail
from date_mapper import ScheduledPost, format_schedule


_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
_MODEL = "claude-sonnet-4-6"


# ── Reference loader ──────────────────────────────────────────────────────────

def load_references() -> dict:
    """
    Load the 3 campaign and 3 DM reference examples from references/.
    Returns a dict with keys 'campaigns' and 'dms', each a list of 3 strings.
    Missing files are replaced with a placeholder notice.
    """
    refs: dict = {"campaigns": [], "dms": []}
    for i in range(1, 4):
        for key, prefix in [("campaigns", "campaign"), ("dms", "dm")]:
            path = config.REFERENCES_DIR / f"{prefix}_{i}.md"
            if path.exists():
                refs[key].append(path.read_text(encoding="utf-8"))
            else:
                refs[key].append(
                    f"[Reference {prefix}_{i} not yet provided — "
                    f"drop the file at references/{prefix}_{i}.md]"
                )
    return refs


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_final_content(
    detail: WebinarDetail,
    post_schedule: list[ScheduledPost],
) -> tuple[str, str]:
    """
    Full pipeline: template → 3 drafts → merge.
    Returns (ad_campaign_markdown, dm_sequence_markdown).
    """
    refs = load_references()
    base = _build_base_template(detail, post_schedule)

    print("[Content] Generating 3 ad campaign drafts...")
    campaign_drafts = [
        _generate_campaign_draft(base, refs["campaigns"][i], i + 1)
        for i in range(3)
    ]

    print("[Content] Generating 3 DM sequence drafts...")
    dm_drafts = [
        _generate_dm_draft(base, refs["dms"][i], i + 1)
        for i in range(3)
    ]

    print("[Content] Merging campaign drafts...")
    final_campaign = _merge_drafts(campaign_drafts, base, "ad_campaign")

    print("[Content] Merging DM drafts...")
    final_dm = _merge_drafts(dm_drafts, base, "dm_sequence")

    return final_campaign, final_dm


# ── Base template ─────────────────────────────────────────────────────────────

def _build_base_template(detail: WebinarDetail, post_schedule: list[ScheduledPost]) -> str:
    speakers_block = "\n".join(
        f"  - {s.name} — {s.title} ({s.company})"
        for s in detail.speakers
    )
    schedule_block = format_schedule(post_schedule)
    campaign_length = len(post_schedule)

    return f"""# Webinar Brief

**Title:** {detail.title}
**Date:** {detail.date} at {detail.time}
**Registration URL:** {detail.registration_url}
**Primary Client:** {detail.primary_client}
**All Companies Involved:** {', '.join(detail.all_clients)}

## Speakers
{speakers_block}

## Overview
{detail.overview}

## What Attendees Will Learn
{detail.learning_outcomes}

## Challenges Addressed
{detail.challenges}

## Post Schedule ({campaign_length} posts)
{schedule_block}
"""


# ── Draft generation ──────────────────────────────────────────────────────────

def _generate_campaign_draft(base: str, reference: str, draft_num: int) -> str:
    prompt = f"""You are a B2B pharmaceutical marketing specialist.

Using the webinar brief below as your content source, and the reference LinkedIn ad campaign as your stylistic and structural guide, write a complete LinkedIn ad campaign.

Requirements:
- One post per scheduled date in the brief (see Post Schedule)
- Each post must reference its scheduled date in the format: **[Post N — DD Mon YYYY (Day)]**
- Mix of post types appropriate for a B2B pharma audience: announcement, speaker spotlight, topic teaser, key insight, urgency, day-before
- The reference is inspiration and standard — do not copy it verbatim. Adapt the tone, structure and quality to this specific webinar
- Include suggested image/creative direction for each post in italics
- End with **Targeting Recommendations** (job titles, industries, seniority, skills)

---
## WEBINAR BRIEF
{base}

---
## REFERENCE CAMPAIGN (Draft {draft_num} anchor)
{reference}

---

Write the complete {draft_num}{'st' if draft_num == 1 else 'nd' if draft_num == 2 else 'rd'} draft ad campaign now:"""

    msg = _client.messages.create(
        model=_MODEL,
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _generate_dm_draft(base: str, reference: str, draft_num: int) -> str:
    prompt = f"""You are a B2B pharmaceutical marketing specialist.

Using the webinar brief below as your content source, and the reference LinkedIn DM sequence as your stylistic and structural guide, write a complete 5-message LinkedIn DM sequence.

Requirements:
- Message 1: Connection request note (max 300 characters)
- Message 2: First DM — warm, value-led (sent 1 day after connection accepted)
- Message 3: Follow-up — low pressure, references webinar value (3 days later if no reply)
- Message 4: Last-chance — urgency, brief (1 day before webinar)
- Message 5: Post-webinar — thank-you / recording follow-up (1 day after)
- Tone: professional, peer-to-peer, pharma/biotech literate
- The reference is inspiration — do not copy verbatim. Adapt to this specific webinar's content

---
## WEBINAR BRIEF
{base}

---
## REFERENCE DM SEQUENCE (Draft {draft_num} anchor)
{reference}

---

Write the complete {draft_num}{'st' if draft_num == 1 else 'nd' if draft_num == 2 else 'rd'} draft DM sequence now:"""

    msg = _client.messages.create(
        model=_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


# ── Merge ─────────────────────────────────────────────────────────────────────

def _merge_drafts(drafts: list[str], base: str, content_type: str) -> str:
    type_label = "LinkedIn ad campaign" if content_type == "ad_campaign" else "LinkedIn DM sequence"
    drafts_block = "\n\n".join(
        f"### Draft {i + 1}\n{d}" for i, d in enumerate(drafts)
    )

    prompt = f"""You are a senior B2B pharmaceutical marketing strategist.

Below are 3 draft versions of a {type_label} for the following webinar:

{base}

---
{drafts_block}

---

Your task: produce one **superior final {type_label}** by merging the best elements from all 3 drafts.

Merge principles:
- Select the strongest headlines, hooks and calls-to-action from across the drafts
- Preserve the most clinically accurate and audience-relevant language
- Ensure structural coherence — the final output should read as one unified piece, not a patchwork
- Maintain all post date references exactly as they appear in the drafts
- The final result should be clearly better than any single draft alone

Output only the final {type_label}. No preamble, no commentary."""

    msg = _client.messages.create(
        model=_MODEL,
        max_tokens=3500,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text
