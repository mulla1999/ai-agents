"""When automatic actions happen, in the user's timezone.

Applications and recruiter emails sent early on a working morning sit at the top of a recruiter's
inbox when they start reviewing, and a role that is days old has usually been shortlisted already.
So by default:

* discovery runs from 06:00 to 22:00, so new postings are found and prepared before the morning
* automatic applications and emails go out only in send windows (Mon–Fri 09:30–12:30 and
  14:00–16:30), and never sooner than ``auto_review_minutes`` after they were prepared, so there is
  time to look and cancel
* anything you approve yourself is sent at once; the windows only pace automatic actions
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..domain import AutomationPolicy


def _parse(window: str) -> tuple[time, time]:
    start, end = window.split("-")
    return time.fromisoformat(start.strip()), time.fromisoformat(end.strip())


def in_window(now_utc: datetime, policy: AutomationPolicy) -> bool:
    local = now_utc.astimezone(ZoneInfo(policy.timezone))
    if local.weekday() not in policy.send_days:
        return False
    return any(start <= local.time() < end for start, end in map(_parse, policy.send_windows))


def next_send_time(earliest_utc: datetime, policy: AutomationPolicy) -> datetime:
    """The first moment at or after ``earliest_utc`` that falls inside a send window."""
    zone = ZoneInfo(policy.timezone)
    local = earliest_utc.astimezone(zone)
    windows = sorted(map(_parse, policy.send_windows))
    for day in range(8):
        date = (local + timedelta(days=day)).date()
        if date.weekday() not in policy.send_days:
            continue
        for start, end in windows:
            opens = datetime.combine(date, start, zone)
            closes = datetime.combine(date, end, zone)
            if local < closes:
                return max(local, opens).astimezone(earliest_utc.tzinfo)
    return earliest_utc  # no usable window configured: do not hold anything back


def discovery_allowed(now_utc: datetime, policy: AutomationPolicy) -> bool:
    start, end = _parse(policy.discovery_hours)
    local = now_utc.astimezone(ZoneInfo(policy.timezone)).time()
    return start <= local < end if start <= end else (local >= start or local < end)
