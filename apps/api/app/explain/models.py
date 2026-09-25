"""Explanation domain models, independent of the HTTP API."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class VenueEffect(BaseModel):
    venue: str | None = None
    previous_known_venue: str | None = None
    transition_from_previous: bool = False
    penalty_points: int = 0
    message: str


class ScheduleFit(BaseModel):
    fixed: bool
    previous_session_id: str | None = None
    next_session_id: str | None = None
    blocked_time_clear: bool = True
    daily_limit_respected: bool = True
    message: str


class DisplacedCandidate(BaseModel):
    session_id: str
    title: str
    relevance_score: int
    rejection_reason: str


class SessionExplanation(BaseModel):
    session_id: str
    code: str | None = None
    title: str
    final_relevance_score: int
    text_relevance_score: int
    preference_score: int
    matched_terms: list[str] = Field(default_factory=list)
    field_scores: dict[str, int] = Field(default_factory=dict)
    matched_interests: list[str] = Field(default_factory=list)
    matched_preferred_services: list[str] = Field(default_factory=list)
    matched_preferred_topics: list[str] = Field(default_factory=list)
    matched_desired_levels: list[str] = Field(default_factory=list)
    matched_learning_goals: list[str] = Field(default_factory=list)
    depth_bonus: int = 0
    preference_contributions: dict[str, int] = Field(default_factory=dict)
    penalties: dict[str, int] = Field(default_factory=dict)
    venue_effect: VenueEffect
    schedule_fit: ScheduleFit
    displaced_candidates: list[DisplacedCandidate] = Field(default_factory=list)


class RejectedExplanation(BaseModel):
    session_id: str
    code: str | None = None
    title: str
    relevance_score: int
    reason: str
    conflicting_session_ids: list[str] = Field(default_factory=list)
    important: bool = False
    message: str


class ScheduleInsight(BaseModel):
    code: str
    message: str
    day: date | None = None
    count: int | None = None


class BlockedTimeUsage(BaseModel):
    configured_blocks: int
    configured_minutes: int
    excluded_candidate_count: int


class ScheduleMetrics(BaseModel):
    selected_session_count: int
    sessions_per_day: dict[str, int]
    venue_transitions_per_day: dict[str, int]
    total_venue_transitions: int
    rejected_high_scoring_conflicts: int
    high_score_threshold: int | None = None
    days_at_daily_limit: list[str]
    blocked_time_usage: BlockedTimeUsage
    fixed_session_count: int
    total_selected_utility: float
    candidate_count: int
    candidate_cap_excluded_count: int


class GoalCoverage(BaseModel):
    label: str
    kind: Literal["interest", "learning_goal"]
    percentage: int = Field(ge=0, le=100)
    selected_opportunity_score: int
    available_opportunity_score: int
    selected_session_ids: list[str] = Field(default_factory=list)
    available_candidate_count: int
    status: Literal["covered", "uncovered", "no_opportunity"]


class ScheduleExplanation(BaseModel):
    sessions: list[SessionExplanation]
    rejected: list[RejectedExplanation]
    insights: list[ScheduleInsight]
    goal_coverage: dict[str, GoalCoverage]
    metrics: ScheduleMetrics
