"""Defensive AWS GetSchedule response adapter."""

from datetime import UTC, datetime

from app.schedule.models import AttendeeSchedule, PersonalTime


class ScheduleNormalizationError(ValueError):
    """A schedule response cannot be trusted as a complete attendee schedule."""


def normalize_schedule(payload: object) -> AttendeeSchedule:
    """Convert the published GetSchedule response into Pathfinder models."""
    if not isinstance(payload, dict) or not isinstance(payload.get("schedule"), dict):
        raise ScheduleNormalizationError("GetSchedule response has no schedule object")
    raw = payload["schedule"]
    reserved = _session_ids(raw.get("reserved"), "reserved")
    favorites = _session_ids(raw.get("favorites"), "favorites")
    personal_entries = raw.get("personalTime")
    if not isinstance(personal_entries, list):
        raise ScheduleNormalizationError("schedule.personalTime must be a list")
    personal_time = [
        _personal_time(entry, index) for index, entry in enumerate(personal_entries)
    ]
    return AttendeeSchedule(
        reserved_session_ids=reserved,
        favorite_session_ids=favorites,
        personal_time=personal_time,
    )


def _session_ids(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ScheduleNormalizationError(f"schedule.{field} must be a list")
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ScheduleNormalizationError(
                f"schedule.{field}[{index}] must be a session ID"
            )
        session_id = item.strip()
        if session_id not in seen:
            seen.add(session_id)
            result.append(session_id)
    return result


def _personal_time(value: object, index: int) -> PersonalTime:
    if not isinstance(value, dict):
        raise ScheduleNormalizationError(
            f"schedule.personalTime[{index}] must be an object"
        )
    identifier = _required_text(value.get("personalTimeId"), index, "personalTimeId")
    start = _utc_datetime(value.get("startDateTime"), index, "startDateTime")
    end = _utc_datetime(value.get("endDateTime"), index, "endDateTime")
    if end <= start:
        raise ScheduleNormalizationError(
            f"schedule.personalTime[{index}] has an invalid interval"
        )
    return PersonalTime(
        id=identifier,
        title=_optional_text(value.get("title")) or "Personal time",
        description=_optional_text(value.get("description")),
        location=_optional_text(value.get("location")),
        start_at=start,
        end_at=end,
    )


def _required_text(value: object, index: int, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ScheduleNormalizationError(
            f"schedule.personalTime[{index}] has no valid {field}"
        )
    return text


def _optional_text(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    return None


def _utc_datetime(value: object, index: int, field: str) -> datetime:
    text = _required_text(value, index, field)
    if "T" not in text:
        raise ScheduleNormalizationError(
            f"schedule.personalTime[{index}] has invalid {field}"
        )
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ScheduleNormalizationError(
            f"schedule.personalTime[{index}] has invalid {field}"
        ) from error
    return (
        parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    )
