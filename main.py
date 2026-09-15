"""
CCA — Content Creation Agent
Entry point. Starts the webhook server and monitor loop.
"""

import sys
import time

import config
from scraper import fetch_upcoming_webinars
from state import load_seen, save_seen
from webhook_server import ApprovalBus, WebhookServer
from orchestrator import CCAOrchestrator


def run_monitor(dry_run: bool = False) -> None:
    bus = ApprovalBus()
    server = WebhookServer(config.AGENT_HOST, config.AGENT_PORT, bus)
    server.start()

    orchestrator = CCAOrchestrator(bus)

    print(f"[Monitor] CCA agent started. Poll interval: {config.POLL_INTERVAL}s")
    print(f"[Monitor] Callback URL: {config.AGENT_CALLBACK_URL}")
    print("[Monitor] Scanning for upcoming webinars...\n")

    while True:
        try:
            # Check for a manual trigger first
            triggered = server.trigger_event.is_set()
            if triggered:
                server.trigger_event.clear()
                forced_slug = server.force_slug[0] if server.force_slug else None
                server.force_slug.clear()
                print(f"[Monitor] Manual trigger received. Forced slug: {forced_slug or 'none (scan all)'}")

            webinars = fetch_upcoming_webinars()
            seen = load_seen()

            if triggered and forced_slug:
                # Match webinar by slug prefix
                new_webinars = [w for w in webinars if w.slug == forced_slug or w.slug.startswith(forced_slug)]
                if not new_webinars:
                    print(f"[Monitor] No webinar found matching slug '{forced_slug}'.")
            else:
                new_webinars = [w for w in webinars if w.slug not in seen]

            if new_webinars:
                print(f"[Monitor] {len(new_webinars)} webinar(s) to process.")
                for listing in new_webinars:
                    if dry_run:
                        print(f"[DRY RUN] Would process: {listing.title} ({listing.date})")
                        seen = load_seen()
                        save_seen(seen | {listing.slug})
                    else:
                        orchestrator.run(listing)
            else:
                print(f"[Monitor] No new webinars. Next check in {config.POLL_INTERVAL}s.")

        except KeyboardInterrupt:
            print("\n[Monitor] Shutting down...")
            server.stop()
            sys.exit(0)
        except Exception as e:
            print(f"[Monitor] Error during scan: {e}")

        # Ping the hub LinkedIn monitor endpoint so it doesn't need its own cron
        try:
            import urllib.request
            hub_monitor_url = config.HUB_URL.rstrip("/") + "/api/cron/linkedin-monitor"
            req = urllib.request.Request(
                hub_monitor_url,
                headers={"Authorization": f"Bearer {config.HUB_SECRET}"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                print(f"[Monitor] LinkedIn monitor ping: {resp.status}")
        except Exception as e:
            print(f"[Monitor] LinkedIn monitor ping failed (non-fatal): {e}")

        # Wait for poll interval OR a trigger signal (whichever comes first)
        server.trigger_event.wait(timeout=config.POLL_INTERVAL)
        if not server.trigger_event.is_set():
            pass  # normal timeout — continue loop


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    run_monitor(dry_run=dry)
