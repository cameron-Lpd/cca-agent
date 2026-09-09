"""
Maps a webinar date to a 12-post (or 11-post) LinkedIn ad schedule.

Pattern (forward, posts 1–11):
  Mon → Tue → Wed → Tue → Mon → Tue → Wed → Tue → Mon → Tue → Wed
  [Mon-Tue-Wed-Tue] cycle — never the same weekday in consecutive weeks.

Post 12 is always the day before the webinar date.
Posts 1–11 fall one per calendar week, working backwards.
If post 1's date ≤ today the campaign is trimmed to 11 posts (post 1 dropped).
"""

from datetime import date, timedelta
from dataclasses import dataclass

# Weekday indices: Mon=0, Tue=1, Wed=2
_WEEKDAY_NAME = {0: "Monday", 1: "Tuesday", 2: "Wednesday",
                 3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday"}

# Forward day pattern for posts 1–11 (0-indexed, Mon=0)
# Mon Tue Wed Tue Mon Tue Wed Tue Mon Tue Wed
POST_DAY_PATTERN = [0, 1, 2, 1, 0, 1, 2, 1, 0, 1, 2]


@dataclass
class ScheduledPost:
    post_number: int        # 1–12 (or 2–12 for 11-post campaigns)
    date: date
    day_name: str
    is_last: bool = False   # True for post 12 (day-before post)

    def to_dict(self) -> dict:
        return {
            "post_number": self.post_number,
            "date": self.date.isoformat(),
            "day": self.day_name,
            "is_last": self.is_last,
        }


def map_post_dates(
    webinar_date: date,
    today: date | None = None,
) -> list[ScheduledPost]:
    """
    Returns the full post schedule for a webinar.
    If post 1 would fall on or before today, it is dropped (11-post campaign).
    """
    if today is None:
        today = date.today()

    # Post 12: day before the webinar
    post_12_date = webinar_date - timedelta(days=1)
    post_12_iso = post_12_date.isocalendar()  # (year, week, weekday)

    posts: list[ScheduledPost] = []

    iso_year, iso_week = post_12_iso[0], post_12_iso[1]

    # Assign posts 11 → 1 by walking backwards one ISO week at a time
    for i in range(10, -1, -1):          # i = 10 (post 11) down to 0 (post 1)
        post_num = i + 1                  # 11 down to 1
        iso_year, iso_week = _prev_iso_week(iso_year, iso_week)
        weekday = POST_DAY_PATTERN[i]     # day for this post position
        post_date = _date_of_weekday_in_iso_week(iso_year, iso_week, weekday)
        posts.append(ScheduledPost(
            post_number=post_num,
            date=post_date,
            day_name=_WEEKDAY_NAME[weekday],
        ))

    # Reverse to chronological order (post 1 first)
    posts.reverse()

    # Append post 12
    posts.append(ScheduledPost(
        post_number=12,
        date=post_12_date,
        day_name=_WEEKDAY_NAME[post_12_date.weekday()],
        is_last=True,
    ))

    # 11-post rule: drop post 1 if its date is on or before today
    if posts[0].date <= today:
        posts = posts[1:]

    return posts


def format_schedule(posts: list[ScheduledPost]) -> str:
    """Human-readable schedule string for embedding in documents."""
    lines = [f"  Post {p.post_number:>2}: {p.date.strftime('%d %b %Y')} ({p.day_name})"
             + (" <-- day-before post" if p.is_last else "")
             for p in posts]
    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _date_of_weekday_in_iso_week(iso_year: int, iso_week: int, weekday: int) -> date:
    """Return the date of `weekday` (Mon=0) in the given ISO year/week."""
    # ISO week 1 always contains January 4th
    jan4 = date(iso_year, 1, 4)
    week1_monday = jan4 - timedelta(days=jan4.weekday())
    target_monday = week1_monday + timedelta(weeks=iso_week - 1)
    return target_monday + timedelta(days=weekday)


def _prev_iso_week(iso_year: int, iso_week: int) -> tuple[int, int]:
    """Return the ISO (year, week) of the week immediately before the given one."""
    if iso_week > 1:
        return iso_year, iso_week - 1
    # Roll back to the last ISO week of the previous year
    dec28 = date(iso_year - 1, 12, 28)  # Dec 28 is always in the last ISO week
    prev = dec28.isocalendar()
    return prev[0], prev[1]
