"""
CCA — Content Creation Agent
Entry point. Starts the webhook server and monitor loop.
"""

import sys
import time
import threading
import urllib.request

import config
from webhook_server import ApprovalBus, WebhookServer


def _monitor_loop(bus: ApprovalBus, server: WebhookServer, dry_run: bool) -> None:
    from scraper import fetch_upcoming_webinars
    from state import load_seen, save_seen
    from orchestrator import CCAOrchestrator

    orchestrator = CCAOrchestrator(bus)

    print(f"[Monitor] Poll interval: {config.POLL_INTERVAL}s")
    print(f"[Monitor] Callback URL: {config.AGENT_CALLBACK_URL}")

    while True:
        try:
            triggered = server.trigger_event.is_set()
            if triggered:
                server.trigger_event.clear()
                forced_slug = server.force_slug[0] if server.force_slug else None
                server.force_slug.clear()
                print(f"[Monitor] Manual trigger. Forced slug: {forced_slug or 'none'}")
            else:
                forced_slug = None

            webinars = fetch_upcoming_webinars()
            seen = load_seen()

            if triggered and forced_slug:
                new_webinars = [
                    w for w in webinars
                    if w.slug == forced_slug or w.slug.startswith(forced_slug)
                ]
                if not new_webinars:
                    print(f"[Monitor] No webinar found matching slug '{forced_slug}'.")
            else:
                new_webinars = [w for w in webinars if w.slug not in seen]

            if new_webinars:
                print(f"[Monitor] {len(new_webinars)} webinar(s) to process.")
                for listing in new_webinars:
                    if dry_run:
                        print(f"[DRY RUN] Would process: {listing.title}")
                        save_seen(load_seen() | {listing.slug})
                    else:
                        orchestrator.run(listing)
            else:
                print(f"[Monitor] No new webinars. Next check in {config.POLL_INTERVAL}s.")

        except Exception as e:
            print(f"[Monitor] Scan error: {e}")

        # Ping hub linkedin-monitor
        try:
            hub_monitor_url = config.HUB_URL.rstrip("/") + "/api/cron/linkedin-monitor"
            req = urllib.request.Request(
                hub_monitor_url,
                headers={"Authorization": f"Bearer {config.HUB_SECRET}"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                print(f"[Monitor] LinkedIn monitor ping: {resp.status}")
        except Exception as e:
            print(f"[Monitor] LinkedIn monitor ping failed: {e}")

        server.trigger_event.wait(timeout=config.POLL_INTERVAL)


def run(dry_run: bool = False) -> None:
    bus = ApprovalBus()
    server = WebhookServer(config.AGENT_HOST, config.AGENT_PORT, bus)
    server.start()
    print(f"[CCA v3] Webhook server listening on port {config.AGENT_PORT}")

    t = threading.Thread(target=_monitor_loop, args=(bus, server, dry_run), daemon=True)
    t.start()

    # Keep process alive so Railway never kills it
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n[CCA] Shutting down.")
        server.stop()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    run(dry_run=dry)
