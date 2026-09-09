"""
CCA Orchestrator — drives the full workflow for a single newly-detected webinar.

Sequence:
  Gate 1 (hub scrape approval) -> Deep scrape -> Data review -> Date mapping
  -> Content generation -> Hub delivery -> Wait for hub callback
  -> [loop if rejected] -> OneDrive save -> Return to idle
"""

import time
from datetime import datetime

import config
from scraper import WebinarListing, scrape_webinar_detail
from date_mapper import map_post_dates, format_schedule
from content_generator import generate_final_content
from hub_client import deliver_detection_to_hub, deliver_to_hub
from onedrive_client import save_drafts
from state import load_seen, save_seen
from webhook_server import ApprovalBus


class CCAOrchestrator:
    def __init__(self, bus: ApprovalBus):
        self.bus = bus

    def run(self, listing: WebinarListing) -> None:
        print(f"\n{'=' * 60}")
        print(f"[Orchestrator] New webinar: {listing.title}")
        print(f"  Date:   {listing.date}")
        print(f"  Client: {listing.primary_client}")
        print(f"  URL:    {listing.url}")
        print(f"{'=' * 60}\n")

        # ── Gate 1: scrape approval (via hub) ────────────────────────────────
        if not self._gate1_approval(listing):
            print("[Orchestrator] Scrape rejected or timed out. Returning to idle.\n")
            return

        # ── Deep scrape ───────────────────────────────────────────────────────
        print("[Orchestrator] Running deep scrape...")
        detail = scrape_webinar_detail(listing.url)

        # ── Data review (display only) ────────────────────────────────────────
        self._print_data_review(detail)

        # ── Date mapping ──────────────────────────────────────────────────────
        webinar_date = datetime.strptime(detail.date_iso, "%Y-%m-%d").date()
        post_schedule = map_post_dates(webinar_date)
        campaign_len = len(post_schedule)
        print(f"\n[Orchestrator] Post schedule ({campaign_len}-post campaign):")
        print(format_schedule(post_schedule))

        # ── Content generation + hub loop ─────────────────────────────────────
        attempt = 0
        while True:
            attempt += 1
            print(f"\n[Orchestrator] Generating content (attempt {attempt})...")
            ad_campaign, dm_sequence = generate_final_content(detail, post_schedule)

            print("[Orchestrator] Delivering drafts to hub...")
            self.bus.arm_hub()
            deliver_to_hub(ad_campaign, dm_sequence, detail, post_schedule)

            print("[Orchestrator] Waiting for hub approval...")
            decision, _ = self.bus.wait_hub(timeout=config.APPROVAL_TIMEOUT)

            if decision is None:
                print("[Orchestrator] Hub approval timed out. Returning to idle.")
                return

            if decision == "approve":
                print("[Orchestrator] Drafts approved.")
                break

            print(f"[Orchestrator] Drafts rejected (attempt {attempt}). Regenerating...")

        # ── OneDrive save ─────────────────────────────────────────────────────
        print("\n[Orchestrator] Saving to OneDrive...")
        try:
            saved_path = save_drafts(ad_campaign, dm_sequence, detail)
            print(f"[Orchestrator] Saved to: {saved_path}")
        except FileNotFoundError as e:
            print(f"[Orchestrator] OneDrive save failed: {e}")
            print("[Orchestrator] Files not saved — manual save required.")

        # ── Mark webinar as seen ──────────────────────────────────────────────
        seen = load_seen()
        save_seen(seen | {listing.slug})
        print(f"[Orchestrator] Marked '{listing.slug}' as seen.")

        print(f"\n[Orchestrator] Workflow complete. Returning to idle.\n")

    # ── Gate 1 ────────────────────────────────────────────────────────────────

    def _gate1_approval(self, listing: WebinarListing) -> bool:
        print("[Gate 1] Sending detection to hub...")
        self.bus.arm_gate1()
        try:
            deliver_detection_to_hub(listing)
        except Exception as e:
            print(f"[Gate 1] Failed to reach hub: {e}")
            return False

        timeout_h = config.APPROVAL_TIMEOUT // 3600
        print(f"[Gate 1] Waiting for hub decision (timeout: {timeout_h}h)...")
        decision = self.bus.wait_gate1(timeout=config.APPROVAL_TIMEOUT)

        if decision is None:
            print("[Gate 1] Timed out — treating as rejection.")
            return False
        return decision == "approve"

    # ── Data review ───────────────────────────────────────────────────────────

    def _print_data_review(self, detail) -> None:
        print("\n[Data Review] -- Scraped webinar data --")
        print(f"  Title:          {detail.title}")
        print(f"  Date:           {detail.date} at {detail.time}")
        print(f"  Primary client: {detail.primary_client}")
        print(f"  All companies:  {', '.join(detail.all_clients)}")
        print(f"  Speakers:")
        for s in detail.speakers:
            print(f"    * {s.name} -- {s.title}")
        print(f"  Overview:       {detail.overview[:120]}...")
        print(f"  Registration:   {detail.registration_url}")
        print("[Data Review] ----------------------------------------\n")
        time.sleep(2)
