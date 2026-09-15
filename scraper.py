"""
Scrapes pharmad-mand.com for webinar listings and individual webinar pages.
"""

import re
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass, field, asdict
from datetime import datetime


WEBINARS_URL = "https://pharmad-mand.com/webinars/"
BASE_URL = "https://pharmad-mand.com"


@dataclass
class Speaker:
    name: str
    title: str
    company: str
    bio: str


@dataclass
class WebinarListing:
    """Lightweight data from the listings page."""
    title: str
    date: str
    date_iso: str
    primary_client: str
    url: str
    slug: str


@dataclass
class WebinarDetail:
    """Full data scraped from the individual webinar page."""
    title: str
    date: str
    date_iso: str
    time: str
    primary_client: str
    all_clients: list[str]
    overview: str
    challenges: str
    learning_outcomes: str
    speakers: list[Speaker]
    registration_url: str
    linkedin_event_url: str
    source_url: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["speakers"] = [asdict(s) for s in self.speakers]
        return d


# ---------------------------------------------------------------------------
# Listings page
# ---------------------------------------------------------------------------

def fetch_upcoming_webinars() -> list[WebinarListing]:
    """Returns only webinars whose date is today or in the future."""
    today = datetime.now().date()
    all_webinars = _fetch_all_listings()
    return [
        w for w in all_webinars
        if _parse_date(w.date_iso) and _parse_date(w.date_iso) >= today
    ]


def _fetch_all_listings() -> list[WebinarListing]:
    resp = _get(WEBINARS_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    webinars: list[WebinarListing] = []
    seen_slugs: set[str] = set()

    for card in soup.find_all("div", class_="e-parent"):
        link = card.find("a", href=re.compile(r"/webinar/[^/]+/"))
        if not link:
            continue
        href = link["href"]
        slug_match = re.search(r"/webinar/([^/]+)/", href)
        if not slug_match:
            continue
        slug = slug_match.group(1)
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        title = _clean_title(_get_class_text(card, "webinartitle"))
        date_raw = _get_class_text(card, "webinardate") or _get_heading_date(card)
        date_iso = _iso_from_display(date_raw)
        primary_client = _get_primary_client(card)
        full_url = href if href.startswith("http") else f"{BASE_URL}{href}"

        webinars.append(WebinarListing(
            title=title or slug.replace("-", " ").title(),
            date=date_raw,
            date_iso=date_iso,
            primary_client=primary_client,
            url=full_url,
            slug=slug,
        ))

    return webinars


# ---------------------------------------------------------------------------
# Individual webinar page (deep scrape)
# ---------------------------------------------------------------------------

def scrape_webinar_detail(url: str) -> WebinarDetail:
    resp = _get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    widgets = soup.find_all(attrs={"data-widget_type": True})

    title = _extract_page_title(widgets)
    date_raw, time_str = _extract_date_time(widgets)
    date_iso = _iso_from_display(date_raw)
    overview = _extract_overview(widgets)
    challenges = _extract_section_after(widgets, "Addressed Challenges")
    learning_outcomes = _extract_section_after(widgets, "WHAT YOU WILL LEARN")
    speakers = _extract_speakers(widgets)
    primary_client, all_clients = _extract_clients(soup, widgets, speakers)
    registration_url = _extract_registration_url(soup, url)
    linkedin_event_url = _extract_linkedin_event(widgets)

    return WebinarDetail(
        title=title,
        date=date_raw,
        date_iso=date_iso,
        time=time_str,
        primary_client=primary_client,
        all_clients=all_clients,
        overview=overview,
        challenges=challenges,
        learning_outcomes=learning_outcomes,
        speakers=speakers,
        registration_url=registration_url,
        linkedin_event_url=linkedin_event_url,
        source_url=url,
    )


def _extract_page_title(widgets: list) -> str:
    # First heading widget that isn't nav or a label like "Date", "Time", etc.
    skip = {"date", "time", "presented by:", "overview", "speakers",
            "reserve your seat", "view linkedin event"}
    for w in widgets:
        if w.get("data-widget_type") == "heading.default":
            text = w.get_text(strip=True)
            if text.lower() not in skip and len(text) > 10:
                return _clean_title(text)
    return ""


def _extract_date_time(widgets: list) -> tuple[str, str]:
    date_str = ""
    time_str = ""
    for i, w in enumerate(widgets):
        if w.get("data-widget_type") != "heading.default":
            continue
        label = w.get_text(strip=True).lower()
        if label == "date" and i + 1 < len(widgets):
            date_str = widgets[i + 1].get_text(strip=True)
        elif label == "time" and i + 1 < len(widgets):
            time_str = widgets[i + 1].get_text(strip=True)
    return date_str, time_str


def _extract_overview(widgets: list) -> str:
    collecting = False
    parts = []
    for w in widgets:
        wtype = w.get("data-widget_type", "")
        text = w.get_text(" ", strip=True)
        if wtype == "heading.default" and text.upper() == "OVERVIEW":
            collecting = True
            continue
        if collecting:
            if wtype == "text-editor.default" and text:
                parts.append(text)
            elif wtype == "heading.default" and text.upper() in (
                "WHAT YOU WILL LEARN", "SPEAKERS", "ADDRESSED CHALLENGES",
                "RESERVE YOUR SEAT"
            ):
                break
    return "\n\n".join(parts)


def _extract_section_after(widgets: list, heading_text: str) -> str:
    collecting = False
    for w in widgets:
        wtype = w.get("data-widget_type", "")
        text = w.get_text(" ", strip=True)
        classes = w.get("class", [])
        if "cardsheading" in classes and heading_text.lower() in text.lower():
            collecting = True
            continue
        if collecting and wtype in ("shortcode.default", "text-editor.default"):
            return text
    return ""


def _extract_speakers(widgets: list) -> list[Speaker]:
    speakers = []
    in_speakers = False
    # Section headings that signal the end of the speakers block
    stop_headings = {
        "reserve your seat", "overview", "what you will learn",
        "addressed challenges", "explore our services",
        "turn registrants into relationships", "pharma d-mand",
        "newsletter", "connect", "offices",
    }
    i = 0
    while i < len(widgets):
        w = widgets[i]
        wtype = w.get("data-widget_type", "")
        text = w.get_text(" ", strip=True)

        if wtype == "heading.default" and text.upper() == "SPEAKERS":
            in_speakers = True
            i += 1
            continue

        if in_speakers:
            if text.lower() in stop_headings:
                break

            # A speaker block: name heading → job title heading (must contain comma) → bio
            if wtype == "heading.default" and _looks_like_person_name(text):
                next_w = widgets[i + 1] if i + 1 < len(widgets) else None
                next_text = next_w.get_text(" ", strip=True) if next_w else ""
                # Require job title heading to contain a comma (role, Company)
                if next_w and next_w.get("data-widget_type") == "heading.default" and "," in next_text:
                    name = text
                    job_title = _clean_title(next_text)
                    company = job_title.split(",")[-1].strip()
                    i += 2
                    bio = ""
                    if i < len(widgets) and "fswp-text-unfold" in widgets[i].get("data-widget_type", ""):
                        bio = widgets[i].get_text(" ", strip=True)
                        i += 1
                    speakers.append(Speaker(name=name, title=job_title, company=company, bio=bio))
                    continue

        i += 1
    return speakers


def _looks_like_person_name(text: str) -> bool:
    words = text.split()
    return (
        2 <= len(words) <= 5
        and not any(c in text for c in ["(", ")", ":", "/"])
        and len(text) < 60
        and not any(w.islower() for w in words)  # all words start uppercase
    )


def _extract_clients(soup, widgets: list, speakers: list[Speaker]) -> tuple[str, list[str]]:
    """
    Primary client = first sponsor logo's company name (from speaker companies).
    All clients = unique companies extracted from speaker job titles.
    Falls back to image alt text / filenames if no speakers found.
    """
    # Derive all clients from speaker company affiliations (most reliable)
    if speakers:
        seen: set[str] = set()
        all_clients: list[str] = []
        for s in speakers:
            if s.company and s.company not in seen:
                seen.add(s.company)
                all_clients.append(s.company)
        # Primary client = company of the first speaker (most prominent)
        primary = all_clients[0] if all_clients else ""
        return primary, all_clients

    # Fallback: image alt tags after "Presented by:" heading
    presented_by_idx = None
    for i, w in enumerate(widgets):
        if w.get("data-widget_type") == "heading.default":
            if "presented by" in w.get_text(strip=True).lower():
                presented_by_idx = i
                break
    if presented_by_idx is None:
        return "", []

    clients: list[str] = []
    for w in widgets[presented_by_idx + 1:]:
        wtype = w.get("data-widget_type", "")
        if wtype == "image.default":
            for img in w.find_all("img"):
                alt = img.get("alt", "").strip()
                if alt and alt.lower() not in ("", "logo"):
                    clients.append(alt)
        elif wtype == "heading.default":
            break

    return (clients[0] if clients else ""), clients


def _name_from_src(src: str) -> str:
    fname = src.split("/")[-1]
    name = re.sub(r"[-_]?(logo|webinar|rgb|web|png|jpg)[-_\d]*", "", fname, flags=re.I)
    name = re.sub(r"\.\w+$", "", name).replace("-", " ").replace("_", " ").strip()
    return name.title() if len(name) > 2 else ""


def _extract_registration_url(soup, page_url: str) -> str:
    # Registration form anchor or the page URL itself (form is on-page)
    form = soup.find("form")
    if form:
        return page_url  # registration is an on-page form
    # Fallback: look for explicit register link
    for a in soup.find_all("a", href=True):
        if "register" in a["href"].lower() or "reserve" in a.get_text(strip=True).lower():
            href = a["href"]
            return href if href.startswith("http") else f"{BASE_URL}{href}"
    return page_url


def _extract_linkedin_event(widgets: list) -> str:
    for w in widgets:
        if w.get("data-widget_type") == "heading.default":
            if "linkedin event" in w.get_text(strip=True).lower():
                a = w.find("a", href=True)
                if a:
                    return a["href"]
    return ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(url: str) -> requests.Response:
    resp = requests.get(url, timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (compatible; pharmad-webinar-agent/1.0)"
    })
    resp.raise_for_status()
    return resp


def _iso_from_display(raw: str) -> str:
    if not raw:
        return ""
    normalised = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", raw.strip())
    # Strip leading weekday name e.g. "Thursday 18 September 2026" → "18 September 2026"
    normalised = re.sub(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s*",
        "", normalised, flags=re.I,
    )
    for fmt in ("%d/%m/%Y", "%d %B %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(normalised, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw.strip()


def _parse_date(iso: str):
    try:
        return datetime.strptime(iso, "%Y-%m-%d").date()
    except ValueError:
        return None


def _clean_title(title: str) -> str:
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", title)


def _get_class_text(card, css_class: str) -> str:
    el = card.find(class_=css_class)
    return el.get_text(strip=True) if el else ""


def _get_heading_date(card) -> str:
    for el in card.find_all(class_="elementor-heading-title"):
        text = el.get_text(strip=True)
        if re.search(r"\d{1,2}(st|nd|rd|th)?\s+\w+\s+\d{4}", text) or re.search(r"\d{1,2}/\d{1,2}/\d{4}", text):
            return text
    return ""


def _get_primary_client(card) -> str:
    img = card.find("img")
    if img:
        alt = img.get("alt", "").strip()
        if alt and alt.lower() not in ("", "logo"):
            return alt
        return _name_from_src(img.get("src", ""))
    return ""
