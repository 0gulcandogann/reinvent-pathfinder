from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.session import Session


class MalformedSessionError(ValueError):
    """A catalog entry lacks the minimum identity needed by Pathfinder."""


def session_identity(payload: object) -> str | None:
    """Read an upstream ID even if the rest of the entry cannot normalize."""
    if not isinstance(payload, dict):
        return None
    return _text(payload.get("sessionId"))


def normalize_session(payload: object) -> Session:
    if not isinstance(payload, dict):
        raise MalformedSessionError("session must be an object")
    session_id = _required_text(session_identity(payload), "sessionId")
    title = _required_text(payload.get("title"), "title")
    start_at, end_at = _session_times(payload.get("sessionTime"))
    return Session(
        id=session_id,
        code=_text(payload.get("abbreviation")),
        title=title,
        abstract=_text(payload.get("abstract")),
        session_type=_text(payload.get("type")),
        level=_text(payload.get("level")),
        tracks=_text_list(payload.get("tracks")),
        topics=_text_list(payload.get("topics")),
        industries=_text_list(payload.get("industries")),
        roles=_text_list(payload.get("roles")),
        services=_text_list(payload.get("services")),
        speakers=_text_list(payload.get("speakers")),
        start_at=start_at,
        end_at=end_at,
        venue=_text(payload.get("venue")),
        room=_text(payload.get("room")),
        reservable=payload.get("isReservable") is True,
        availability=_text(payload.get("seatAvailability")),
    )


def _required_text(value: Any, field: str) -> str:
    result = _text(value)
    if result is None:
        raise MalformedSessionError(f"session has no valid {field}")
    return result


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    return None


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, dict):
            item = item.get("name")
        text = _text(item)
        if text is not None:
            result.append(text)
    return result


def _session_times(value: Any) -> tuple[datetime | None, datetime | None]:
    if not isinstance(value, dict):
        return None, None
    date = _text(value.get("date"))
    time = _text(value.get("time"))
    if date is None or time is None:
        return None, None
    try:
        start = datetime.fromisoformat(f"{date}T{time}")
    except ValueError:
        return None, None
    zone_name = _text(value.get("timezone"))
    if zone_name and start.tzinfo is None:
        try:
            start = start.replace(tzinfo=ZoneInfo(zone_name))
        except ZoneInfoNotFoundError:
            pass  # Retain the event's local time if its timezone is unknown.
    length = _text(value.get("length"))
    if length is None:
        return start, None
    try:
        minutes = int(length)
        if minutes < 0:
            return start, None
        return start, start + timedelta(minutes=minutes)
    except (ValueError, OverflowError):
        return start, None
