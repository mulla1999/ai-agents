from datetime import datetime, timezone

import pytest

from hirefinch.domain import AutomationPolicy
from hirefinch.workflow.timing import discovery_allowed, in_window, next_send_time

IST = AutomationPolicy(timezone="Asia/Kolkata")


def utc(text: str) -> datetime:
    """An IST wall-clock time, as UTC."""
    from zoneinfo import ZoneInfo

    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo("Asia/Kolkata")).astimezone(timezone.utc)


@pytest.mark.parametrize(("earliest", "expected"), [
    ("2026-10-27 08:00", "2026-10-27 09:30"),  # Tuesday, before the morning window
    ("2026-10-27 10:15", "2026-10-27 10:15"),  # inside it
    ("2026-10-27 13:00", "2026-10-27 14:00"),  # lunch: afternoon window
    ("2026-10-30 17:00", "2026-11-02 09:30"),  # Friday evening: Monday morning
    ("2026-10-31 11:00", "2026-11-02 09:30"),  # Saturday
])
def test_next_send_time(earliest, expected):
    assert next_send_time(utc(earliest), IST) == utc(expected)


def test_in_window_and_discovery_hours():
    assert in_window(utc("2026-10-27 11:00"), IST) and not in_window(utc("2026-10-27 12:45"), IST)
    assert not in_window(utc("2026-11-01 11:00"), IST)  # Sunday
    assert discovery_allowed(utc("2026-10-27 06:30"), IST) and not discovery_allowed(utc("2026-10-27 23:00"), IST)
    night = AutomationPolicy(discovery_hours="22:00-06:00")
    assert discovery_allowed(utc("2026-10-27 23:00").replace(), night.model_copy(update={"timezone": "Asia/Kolkata"}))


@pytest.mark.parametrize("bad", [{"send_windows": ["12:00-09:00"]}, {"send_days": [7]}, {"send_days": []},
                                 {"timezone": "Mars/Base"}, {"discovery_hours": "6am-10pm"}])
def test_invalid_timing_policy(bad):
    with pytest.raises(ValueError):
        AutomationPolicy(**bad)
