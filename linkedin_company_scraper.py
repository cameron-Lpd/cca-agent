"""
Fetches recent posts from a LinkedIn company page using LinkedIn's internal
Voyager API with a li_at session cookie (no Marketing Developer Platform needed).

The li_at cookie is a long-lived session token from the user's browser.
Copy it from DevTools → Application → Cookies → .linkedin.com → li_at.
Store it as LINKEDIN_SESSION_COOKIE in Railway env vars (~3 month lifespan).
"""

import json
import requests

_BASE = "https://www.linkedin.com"


def _build_session(li_at: str) -> requests.Session:
    s = requests.Session()
    s.cookies.set("li_at", li_at, domain=".linkedin.com")
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/vnd.linkedin.normalized+json+2.1",
        "Accept-Language": "en-US,en;q=0.9",
        "X-Li-Lang": "en_US",
        "X-Requested-With": "XMLHttpRequest",
        "X-Li-Track": json.dumps({
            "clientVersion": "1.13",
            "mpVersion": "1.13",
            "osName": "web",
            "timezoneOffset": 1,
            "timezone": "Europe/London",
            "deviceFormFactor": "DESKTOP",
        }),
    })
    return s


def _ensure_csrf(s: requests.Session) -> None:
    """Touch the homepage to get JSESSIONID, then derive CSRF token from it."""
    jsessionid = s.cookies.get("JSESSIONID")
    if not jsessionid:
        s.get(_BASE, timeout=10, allow_redirects=True)
        jsessionid = s.cookies.get("JSESSIONID", "")
    csrf = jsessionid.strip('"')
    if csrf:
        s.headers["Csrf-Token"] = csrf


def _extract_images(update: dict) -> list[str]:
    """Extract image URLs from a Voyager post element (up to 4 images)."""
    for key in list(update.keys()):
        if "UpdateV2" in key or "Update" in key:
            update = update[key]
            break

    reshared = update.get("resharedUpdate")
    if isinstance(reshared, dict):
        return _extract_images(reshared)

    content = update.get("content", {})
    if not isinstance(content, dict):
        return []

    # Unwrap typed content key (e.g. com.linkedin.voyager.feed.render.ImageComponent)
    for key in list(content.keys()):
        if key.startswith("com.linkedin."):
            content = content[key]
            break

    urls: list[str] = []

    # Path 1: images list (newer format)
    images = content.get("images", [])
    if isinstance(images, list):
        for img in images:
            if not isinstance(img, dict):
                continue
            url = img.get("originalUrl") or img.get("url") or ""
            if not url:
                for attr in img.get("attributes", []):
                    vi = attr.get("vectorImage", {}) if isinstance(attr, dict) else {}
                    if isinstance(vi, dict) and vi.get("rootUrl"):
                        root = vi["rootUrl"]
                        arts = vi.get("artifacts", [])
                        if arts:
                            best = max(arts, key=lambda a: a.get("width", 0) if isinstance(a, dict) else 0)
                            suffix = best.get("fileIdentifyingUrlPathSegment", "") if isinstance(best, dict) else ""
                            url = root + suffix
                        else:
                            url = root
                        break
            if url and url not in urls:
                urls.append(url)

    # Path 2: contentEntities thumbnails (older format)
    for entity in content.get("contentEntities", []):
        if not isinstance(entity, dict):
            continue
        for thumb in entity.get("thumbnails", []):
            if isinstance(thumb, dict):
                url = thumb.get("resolvedUrl", "")
                if url and url not in urls:
                    urls.append(url)

    return urls[:4]


def _extract_text(update: dict) -> str:
    """Walk the nested Voyager structure to find the post's text content."""
    # Unwrap the typed key if present
    for key in list(update.keys()):
        if "UpdateV2" in key or "Update" in key:
            update = update[key]
            break

    # Path 1: commentary.text.text (most common)
    commentary = update.get("commentary")
    if isinstance(commentary, dict):
        t = commentary.get("text")
        if isinstance(t, dict):
            text = t.get("text", "")
        else:
            text = str(t or "")
        if text:
            return text.strip()

    # Path 2: resharedUpdate.commentary
    reshared = update.get("resharedUpdate")
    if isinstance(reshared, dict):
        return _extract_text(reshared)

    # Path 3: actor description (reposts/shares with no original text)
    actor = update.get("actor", {})
    if isinstance(actor, dict):
        desc = actor.get("description", {})
        if isinstance(desc, dict):
            return desc.get("text", "").strip()

    return ""


def _extract_post(element: dict) -> tuple[str, str, int, list[str]]:
    """Return (urn, text, published_ms, image_urls) from a raw feed element."""
    wrapper = element.get("value", element)

    urn = (
        wrapper.get("updateKey")
        or wrapper.get("urn")
        or element.get("entityUrn", "")
    )

    text = _extract_text(dict(wrapper))
    images = _extract_images(dict(wrapper))

    metadata = wrapper.get("updateMetadata", {})
    published_ms = int(metadata.get("publishedAt", 0)) if isinstance(metadata, dict) else 0
    if not published_ms:
        created = element.get("created")
        if isinstance(created, dict):
            published_ms = int(created.get("time", 0))

    return str(urn), text, published_ms, images


def get_company_posts(org_id: str, li_at: str, count: int = 10) -> list[dict]:
    """
    Fetch recent posts from a LinkedIn company page.
    Returns list of {urn, text, published_ms, published_iso}.

    Raises:
        requests.HTTPError  — 401 if li_at cookie is expired/invalid
        requests.Timeout    — network timeout
    """
    s = _build_session(li_at)
    _ensure_csrf(s)

    resp = s.get(
        f"{_BASE}/voyager/api/feed/updatesV2",
        params={
            "companyIds": f"List({org_id})",
            "q": "companyFeedByIds",
            "count": count,
            "start": 0,
        },
        timeout=15,
    )
    resp.raise_for_status()

    data = resp.json()
    posts = []
    for element in data.get("elements", []):
        urn, text, published_ms, images = _extract_post(element)
        if urn and text:
            from datetime import datetime, timezone
            ts = published_ms / 1000 if published_ms > 1e10 else published_ms
            iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else ""
            posts.append({
                "urn": urn,
                "text": text,
                "published_ms": published_ms,
                "published_iso": iso,
                "images": images,
            })

    return posts
