"""Merge a normalized attendee schedule into local optimization inputs."""

from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from app.catalog.repository import SessionRepository
from app.catalog.search_service import SessionSearchService
from app.explain.models import ScheduleExplanation
from app.explain.service import explain_schedule
from app.models.profile import AttendeeProfile, TimeBlock
from app.models.session import Session
from app.optimizer.models import OptimizedSchedule
from app.optimizer.solve import optimize_schedule
from app.ranking.session_search import SearchFilters
from app.schedule.models import AttendeeSchedule, PersonalTime

DEFAULT_EVENT_TIMEZONE = "America/Los_Angeles"
CANDIDATE_CAP_EXPLANATION_LIMIT = 20


class ScheduleIntegrationError(ValueError):
    """Existing attendee commitments cannot be integrated safely."""


class PlannedSessionItem(BaseModel):
    session: Session
    source: Literal["existing_reserved", "pathfinder_selected"]
    is_favorite: bool = False
    relevance_score: int


class PersonalTimeItem(BaseModel):
    block: PersonalTime
    source: Literal["personal_time"] = "personal_time"
    event_local_start_at: datetime
    event_local_end_at: datetime


class IntegratedSchedule(BaseModel):
    schedule: OptimizedSchedule
    explanation: ScheduleExplanation
    session_items: list[PlannedSessionItem]
    personal_time_items: list[PersonalTimeItem]
    already_reserved_ids: list[str]
    proposed_addition_ids: list[str]
    favorite_session_ids: list[str] = Field(default_factory=list)


class ExistingSchedulePlanner:
    """Resolve local sessions and preserve attendee commitments before M4."""

    def __init__(self, repository: SessionRepository) -> None:
        self.repository = repository
        self.search = SessionSearchService(repository)

    def plan(
        self,
        attendee_schedule: AttendeeSchedule,
        profile: AttendeeProfile,
        *,
        query: str = "",
        filters: SearchFilters | None = None,
        candidate_limit: int = 150,
        event_timezone: str = DEFAULT_EVENT_TIMEZONE,
        event_start: date | None = None,
        event_end: date | None = None,
        daily_limits: dict[date, int] | None = None,
        allowed_candidate_ids: set[str] | None = None,
    ) -> IntegratedSchedule:
        if candidate_limit < 1:
            raise ScheduleIntegrationError("candidate_limit must be positive")
        try:
            zone = ZoneInfo(event_timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ScheduleIntegrationError("unknown event_timezone") from error

        fixed = [
            _event_local_session(session, zone)
            for session in self._resolve_reserved(
                attendee_schedule.reserved_session_ids
            )
        ]
        local_blocks = [
            PersonalTimeItem(
                block=block,
                event_local_start_at=block.start_at.astimezone(zone),
                event_local_end_at=block.end_at.astimezone(zone),
            )
            for block in attendee_schedule.personal_time
        ]
        merged_profile = profile.model_copy(deep=True)
        for item in local_blocks:
            for block in _calendar_blocks(
                item.event_local_start_at, item.event_local_end_at
            ):
                if not any(
                    _same_event_block(existing, block)
                    for existing in merged_profile.blocked_times
                ):
                    merged_profile.blocked_times.append(block)

        ranked = self.search.search(
            query,
            filters,
            profile=merged_profile,
            limit=candidate_limit + CANDIDATE_CAP_EXPLANATION_LIMIT,
        )
        event_local_hits = [
            hit.model_copy(update={"session": _event_local_session(hit.session, zone)})
            for hit in ranked.results
            if allowed_candidate_ids is None or hit.session.id in allowed_candidate_ids
        ]
        optimized = optimize_schedule(
            event_local_hits[:candidate_limit],
            merged_profile,
            fixed_sessions=fixed,
            event_start=event_start,
            event_end=event_end,
            daily_limits=daily_limits,
        )
        explanation = explain_schedule(
            optimized,
            merged_profile,
            capped_candidates=event_local_hits[candidate_limit:],
            candidate_total=ranked.total,
            candidate_limit=candidate_limit,
        )
        reserved_ids = set(attendee_schedule.reserved_session_ids)
        favorite_ids = set(attendee_schedule.favorite_session_ids)
        session_items = [
            PlannedSessionItem(
                session=item.hit.session,
                source=(
                    "existing_reserved"
                    if item.hit.session.id in reserved_ids
                    else "pathfinder_selected"
                ),
                is_favorite=item.hit.session.id in favorite_ids,
                relevance_score=item.hit.score,
            )
            for item in optimized.selected_sessions
        ]
        return IntegratedSchedule(
            schedule=optimized,
            explanation=explanation,
            session_items=session_items,
            personal_time_items=local_blocks,
            already_reserved_ids=[
                item.session.id
                for item in session_items
                if item.source == "existing_reserved"
            ],
            proposed_addition_ids=[
                item.session.id
                for item in session_items
                if item.source == "pathfinder_selected"
            ],
            favorite_session_ids=list(attendee_schedule.favorite_session_ids),
        )

    def _resolve_reserved(self, session_ids: list[str]) -> list[Session]:
        sessions: list[Session] = []
        missing: list[str] = []
        for session_id in dict.fromkeys(session_ids):
            session = self.repository.get(session_id)
            if session is None:
                missing.append(session_id)
            else:
                sessions.append(session)
        if missing:
            raise ScheduleIntegrationError(
                "reserved sessions are missing from the local catalog: "
                + ", ".join(missing)
            )
        return sessions


def _event_local_session(session: Session, zone: ZoneInfo) -> Session:
    """Use one event clock for M4 block comparisons without changing storage."""
    updates = {}
    if session.start_at is not None and session.start_at.utcoffset() is not None:
        updates["start_at"] = session.start_at.astimezone(zone)
    if session.end_at is not None and session.end_at.utcoffset() is not None:
        updates["end_at"] = session.end_at.astimezone(zone)
    return session.model_copy(update=updates) if updates else session


def _calendar_blocks(start: datetime, end: datetime) -> list[TimeBlock]:
    """Split absolute personal time into event-date wall-clock blocks."""
    blocks: list[TimeBlock] = []
    cursor = start
    while cursor < end:
        next_midnight = datetime.combine(
            cursor.date() + timedelta(days=1), time.min, tzinfo=cursor.tzinfo
        )
        segment_end = min(end, next_midnight)
        end_clock = (
            segment_end.time() if segment_end.date() == cursor.date() else time.max
        )
        blocks.append(
            TimeBlock(
                day=cursor.date().isoformat(),
                start=cursor.time(),
                end=end_clock,
            )
        )
        cursor = segment_end
    return blocks


def _same_event_block(first: TimeBlock, second: TimeBlock) -> bool:
    """Avoid counting an explicit weekday block twice with matching personal time."""
    if first.start != second.start or first.end != second.end:
        return False
    if first.day.casefold() == second.day.casefold():
        return True
    try:
        return (
            first.day.casefold()
            == date.fromisoformat(second.day).strftime("%A").casefold()
        )
    except ValueError:
        return False
