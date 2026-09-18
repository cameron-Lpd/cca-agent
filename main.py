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


def _check_linkedin_company_posts() -> None:
    """Poll LinkedIn company page for new posts and hit the hub webhook for each one."""
    if not config.LINKEDIN_ORG_ID or not config.LINKEDIN_SESSION_COOKIE:
        return

    from linkedin_company_scraper import get_company_posts
    from state import load_seen_li_urns, save_seen_li_urns

    try:
        posts = get_company_posts(config.LINKEDIN_ORG_ID, config.LINKEDIN_SESSION_COOKIE)
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status == 401:
            print("[LinkedIn] li_at cookie expired — update LINKEDIN_SESSION_COOKIE in Railway.")
        else:
            print(f"[LinkedIn] Failed to fetch company posts: {e}")
        return

    seen_urns = load_seen_li_urns()
    new_posts = [p for p in posts if p["urn"] not in seen_urns]

    if not new_posts:
        print(f"[LinkedIn] No new company posts (checked {len(posts)}).")
        return

    print(f"[LinkedIn] {len(new_posts)} new post(s) detected.")
    hub_webhook = config.HUB_URL.rstrip("/") + "/api/webhooks/company-post"

    for post in new_posts:
        try:
            req = urllib.request.Request(
                hub_webhook,
                data=__import__("json").dumps({
                    "post_text": post["text"],
                    "post_time": post["published_iso"],
                    "post_urn": post["urn"],
                    "images": post.get("images", []),
                }).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Secret": config.HUB_SECRET,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = __import__("json").loads(resp.read())
                if body.get("matched"):
                    print(f"[LinkedIn] Post matched '{body['campaign']['name']}' "
                          f"(score {body['campaign']['score']:.2f}) — "
                          f"{body['employeeCount']} employee(s) scheduled.")
                else:
                    print(f"[LinkedIn] Post sent to hub but no campaign matched.")
        except Exception as e:
            print(f"[LinkedIn] Webhook delivery failed for {post['urn']}: {e}")

    save_seen_li_urns(seen_urns | {p["urn"] for p in new_posts})


def _fire_due_posts() -> None:
    """Tell the hub to fire any employee posts whose scheduled time has arrived."""
    import urllib.request, urllib.error
    url = config.HUB_URL.rstrip("/") + "/api/cron/post"
    try:
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {config.HUB_CRON_SECRET}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = __import__("json").loads(resp.read())
            fired = body.get("fired", 0)
            if fired:
                print(f"[PostFire] Fired {body.get('posted', 0)} posts, "
                      f"{body.get('failed', 0)} failed.")
    except urllib.error.HTTPError as e:
        print(f"[PostFire] Hub returned {e.code}: {e.reason}")
    except Exception as e:
        print(f"[PostFire] Error calling hub cron: {e}")


def _post_fire_loop() -> None:
    """Run _fire_due_posts every 15 minutes independently of the webinar poll."""
    POST_FIRE_INTERVAL = 900  # 15 minutes
    while True:
        time.sleep(POST_FIRE_INTERVAL)
        _fire_due_posts()


def _monitor_loop(bus: ApprovalBus, server: WebhookServer, dry_run: bool) -> None:
    from scraper import fetch_upcoming_webinars, scrape_webinar_detail
    from state import load_seen, save_seen
    from orchestrator import CCAOrchestrator
    from onedrive_client import has_existing_campaign

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
                candidates = [
                    w for w in webinars
                    if w.slug == forced_slug or w.slug.startswith(forced_slug)
                ]
                if not candidates:
                    print(f"[Monitor] No webinar found matching slug '{forced_slug}'.")
                new_webinars = candidates
            else:
                # Skip webinars already in state AND already covered by an OneDrive campaign doc
                new_webinars = []
                for w in webinars:
                    if w.slug in seen:
                        continue
                    try:
                        detail = scrape_webinar_detail(w.url)
                        if has_existing_campaign(w.title, detail.all_clients or [w.primary_client]):
                            print(f"[Monitor] Skipping '{w.title}' — campaign doc already exists in OneDrive.")
                            save_seen(load_seen() | {w.slug})
                            continue
                    except Exception as e:
                        print(f"[Monitor] Could not check OneDrive for '{w.title}': {e}")
                    new_webinars.append(w)

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

        # Check LinkedIn company page for new posts
        _check_linkedin_company_posts()

        server.trigger_event.wait(timeout=config.POLL_INTERVAL)


def run(dry_run: bool = False) -> None:
    bus = ApprovalBus()
    server = WebhookServer(config.AGENT_HOST, config.AGENT_PORT, bus)
    server.start()
    print(f"[CCA v3] Webhook server listening on port {config.AGENT_PORT}")

    t = threading.Thread(target=_monitor_loop, args=(bus, server, dry_run), daemon=True)
    t.start()

    fire_t = threading.Thread(target=_post_fire_loop, daemon=True)
    fire_t.start()

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
