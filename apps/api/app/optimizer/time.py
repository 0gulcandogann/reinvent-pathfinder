"""Time validation and half-open interval operations for schedules."""

from dataclasses import dataclass
from datetime import date, datetime, tzinfo

from app.models.profile import WEEKDAY_NAMES, TimeBlock
from app.models.session import Session


@dataclass(frozen=True)
class SessionInterval:
    start: datetime
    end: datetime
    day: date


def is_aware(value: datetime) -> bool:
    return value.utcoffset() is not None


def session_interval(
    session: Session, *, expect_aware: bool, event_timezone: tzinfo | None
) -> tuple[SessionInterval | None, str | None]:
    """Validate a session in the event's local timezone, without changing it."""
    start, end = session.start_at, session.end_at
    if start is None or end is None:
        return None, "invalid_time"
    if is_aware(start) != is_aware(end) or is_aware(start) != expect_aware:
        return None, "timezone_mismatch"
    if event_timezone is not None:
        start = start.astimezone(event_timezone)
        end = end.astimezone(event_timezone)
    if end <= start:
        return None, "invalid_time"
    if start.date() != end.date():
        return None, "cross_day_session"
    return SessionInterval(start=start, end=end, day=start.date()), None


def intervals_overlap(first: SessionInterval, second: SessionInterval) -> bool:
    """Half-open intervals overlap only when they share positive duration."""
    if is_aware(first.start) != is_aware(second.start):
        raise ValueError("cannot compare naive and aware schedule intervals")
    return first.start < second.end and second.start < first.end


def blocked_time_overlaps(interval: SessionInterval, blocks: list[TimeBlock]) -> bool:
    """Interpret blocks as wall-clock time in the event's local timezone."""
    day_name = WEEKDAY_NAMES[interval.day.weekday()].casefold()
    date_name = interval.day.isoformat()
    start = interval.start.time()
    end = interval.end.time()
    return any(
        (block.day.casefold() == day_name or block.day == date_name)
        and start < block.end
        and block.start < end
        for block in blocks
    )
