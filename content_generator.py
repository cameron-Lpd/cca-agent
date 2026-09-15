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


_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY or "dummy-key-not-used-in-mock-mode")
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
    mock: bool = False,
) -> tuple[str, str]:
    """
    Full pipeline: template → 3 drafts → merge.
    Returns (ad_campaign_markdown, dm_sequence_markdown).
    Pass mock=True to skip API calls and return placeholder content for pipeline testing.
    """
    if mock or not config.ANTHROPIC_API_KEY:
        print("[Content] MOCK MODE — returning placeholder content (no API call).")
        reg_url = detail.registration_url or detail.source_url
        client = detail.primary_client or "our client"

        ad_posts = []
        for i, post in enumerate(post_schedule, 1):
            try:
                from datetime import datetime as _dt
                d = _dt.strptime(str(post.date), "%Y-%m-%d")
                day = d.day
                suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
                date_str = f"{day}{suffix} {d.strftime('%B %Y')}"
            except Exception:
                date_str = str(post.date)

            ad_posts.append(
                f"POST {i} WC {date_str}\n"
                f"[MOCK] Join {client} for '{detail.title}' — discover expert insights on this critical topic.\n\n"
                f"📅 {detail.date}\n"
                f"⏰ {detail.time}\n"
                f"🔗 Register now: {reg_url}\n\n"
                f"What challenges are you currently facing in this area?\n"
                f"#{client.replace(' ', '')} #PharmaDmand #Webinar #LifeSciences"
            )
        ad = "\n\n".join(ad_posts)

        dm = (
            f"MESSAGE 1 - Connection & Introduction\n"
            f"Hi [First Name],\n"
            f"[MOCK] Great to connect. We're partnering with {client} on '{detail.title}' — given your background, I thought this might be of interest. Keen to join?\n"
            f"Best, [Your name]\n\n"
            f"MESSAGE 2 - First Follow-Up\n"
            f"Hi [First Name],\n"
            f"[MOCK] Wanted to follow up. The session covers key aspects of {detail.title} and includes insights from leading experts in the field.\n"
            f"Best, [Your name]\n\n"
            f"MESSAGE 3 - Speaker Spotlight\n"
            f"Hi [First Name],\n"
            f"[MOCK] The speakers bring real depth to this topic — practical, peer-level content you can apply directly. Would this be of interest?\n"
            f"Best, [Your name]\n\n"
            f"MESSAGE 4 - Challenge Focus\n"
            f"Hi [First Name],\n"
            f"[MOCK] If you're working through challenges in this area, this session offers early-stage insights without committing significant time upfront. Shall I send you the link?\n"
            f"Best, [Your name]\n\n"
            f"MESSAGE 5 - Final Invitation\n"
            f"Hi [First Name],\n"
            f"[MOCK] Last chance — '{detail.title}' is on {detail.date}. A great opportunity to hear from {client} directly. Hope to see you there.\n"
            f"Best, [Your name]"
        )
        return ad, dm

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
    prompt = f"""You are a B2B pharmaceutical marketing specialist writing LinkedIn posts for Pharma D-mand.

Using the webinar brief below as your content source, and the reference LinkedIn ad campaign as your stylistic and structural guide, write a complete LinkedIn ad campaign.

FORMAT RULES — follow these exactly, matching the reference style:
- One post per scheduled date in the brief (see Post Schedule)
- Each post header must be exactly: POST N WC [date as ordinal e.g. "22nd April 2026"]
  Example: POST 1 WC 18th September 2026
- Post body: 2–4 short paragraphs of engaging B2B copy. No markdown headers, no bullet points in the body (use natural prose). Bullet lists only for key learnings/agenda items in select posts.
- After the body, include this emoji block on separate lines:
  📅 [webinar date as ordinal e.g. "18th September 2026"]
  ⏰ [webinar time with timezones e.g. "16:00 CET | 10:00 ET"]
  🔗 [Register verb e.g. "Register now:", "Register here:", "Save your seat:"] [registration URL]
- End each post with a single engaging question relevant to the post topic (no hashtag on this line)
- Hashtags on the final line: 4–5 relevant tags including #PharmaDmand and the client company tag
- Leave one blank line between posts
- No markdown bold/italic, no section headers, no creative direction notes, no targeting section

MIX of post types across the campaign: announcement, speaker spotlight, topic teaser, key insight, two-weeks-to-go, day-before urgency.

---
## WEBINAR BRIEF
{base}

---
## REFERENCE CAMPAIGN (Draft {draft_num} anchor — match this style and quality, not content)
{reference}

---

Write the complete {draft_num}{'st' if draft_num == 1 else 'nd' if draft_num == 2 else 'rd'} draft ad campaign now. Output only the posts, nothing else:"""

    msg = _client.messages.create(
        model=_MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _generate_dm_draft(base: str, reference: str, draft_num: int) -> str:
    prompt = f"""You are a B2B pharmaceutical marketing specialist writing LinkedIn DMs for Pharma D-mand.

Using the webinar brief below as your content source, and the reference DM sequence as your stylistic and structural guide, write a complete 5-message LinkedIn DM sequence.

FORMAT RULES — follow these exactly, matching the reference style:
- Each message header: MESSAGE N - [Short descriptive title]
  Example: MESSAGE 1 - Connection & Introduction
- Salutation: Hi [First Name],
- Body: 2–4 short sentences. Conversational, peer-to-peer, no jargon overload. Do not use markdown.
- Sign-off on its own line, e.g.: Best, [Your name]
- Leave one blank line between messages

MESSAGE PURPOSES:
- MESSAGE 1: Connection request / introduction — brief, warm, mention the webinar and why it suits them. Under 300 characters total.
- MESSAGE 2: First follow-up — expand on the webinar value, reference a specific learning outcome or speaker.
- MESSAGE 3: Speaker/learning spotlight — highlight a specific speaker or topic that would resonate.
- MESSAGE 4: Challenge focus — relate the webinar content to a pain point they likely face. Offer the link.
- MESSAGE 5: Final invitation — urgency, last chance, keep it brief and friendly.

Tone: professional but human, peer-to-peer, pharma/biotech literate. Never salesy or pushy.

---
## WEBINAR BRIEF
{base}

---
## REFERENCE DM SEQUENCE (Draft {draft_num} anchor — match this style and quality, not content)
{reference}

---

Write the complete {draft_num}{'st' if draft_num == 1 else 'nd' if draft_num == 2 else 'rd'} draft DM sequence now. Output only the messages, nothing else:"""

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

    if content_type == "ad_campaign":
        format_reminder = """FORMAT TO PRESERVE:
- Post headers: POST N WC [ordinal date] — keep exactly as written in the drafts
- Emoji block per post: 📅 date / ⏰ time / 🔗 registration link
- One engagement question per post (no hashtag on same line)
- Hashtags on final line of each post
- Plain prose body — no markdown headers or bold text"""
    else:
        format_reminder = """FORMAT TO PRESERVE:
- Message headers: MESSAGE N - [Title] — keep exactly as written in the drafts
- Salutation: Hi [First Name],
- Sign-off: Best, [Your name]
- Plain prose — no markdown"""

    prompt = f"""You are a senior B2B pharmaceutical marketing strategist.

Below are 3 draft versions of a {type_label} for the following webinar:

{base}

---
{drafts_block}

---

Your task: produce one superior final {type_label} by merging the best elements from all 3 drafts.

Merge principles:
- Select the strongest hooks, copy, and calls-to-action from across the drafts
- Preserve the most clinically accurate and audience-relevant language
- Ensure structural coherence — the final output should read as one unified piece, not a patchwork
- The final result should be clearly better than any single draft alone

{format_reminder}

Output only the final {type_label}. No preamble, no commentary, no explanation."""

    msg = _client.messages.create(
        model=_MODEL,
        max_tokens=3500,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text
