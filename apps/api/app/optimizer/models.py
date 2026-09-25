"""Optimizer domain output, independent of HTTP and persistence."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.ranking.session_search import SearchHit


class ScheduledSession(BaseModel):
    hit: SearchHit
    fixed: bool = False
    selection_reason: str
    event_local_start_at: datetime | None = None
    event_local_end_at: datetime | None = None


class RejectedSession(BaseModel):
    hit: SearchHit
    reason: str
    conflicting_with: list[str] = Field(default_factory=list)


class ScheduleAlternative(BaseModel):
    hit: SearchHit
    rejected_reason: str
    replaces_session_id: str


class AppliedConstraints(BaseModel):
    blocked_time_count: int
    max_sessions_per_day: int | None
    fixed_session_count: int
    minimize_venue_changes: bool
    event_start: date | None = None
    event_end: date | None = None
    daily_limits: dict[str, int] = Field(default_factory=dict)


class OptimizedSchedule(BaseModel):
    selected_sessions: list[ScheduledSession]
    rejected_sessions: list[RejectedSession]
    alternatives: dict[str, list[ScheduleAlternative]]
    score: float
    relevance_total: int
    venue_penalty: int
    venue_transitions: int
    sessions_per_day: dict[str, int]
    rejected_conflict_count: int
    constraints: AppliedConstraints
    warnings: list[str]
    candidate_count: int
