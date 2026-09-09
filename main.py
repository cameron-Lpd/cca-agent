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
            webinars = fetch_upcoming_webinars()
            seen = load_seen()

            new_webinars = [w for w in webinars if w.slug not in seen]

            if new_webinars:
                print(f"[Monitor] {len(new_webinars)} new webinar(s) detected.")
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

        time.sleep(config.POLL_INTERVAL)


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    run_monitor(dry_run=dry)
