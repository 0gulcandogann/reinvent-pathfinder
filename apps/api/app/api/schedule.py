"""Thin HTTP adapter for local deterministic schedule optimization."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.search import RecommendationFilters, get_search_service
from app.catalog.search_service import SessionSearchService
from app.explain.models import ScheduleExplanation
from app.explain.service import explain_schedule
from app.models.profile import AttendeeProfile
from app.models.session import Session
from app.optimizer.models import OptimizedSchedule
from app.optimizer.solve import ScheduleConstraintError, optimize_schedule
from app.ranking.session_search import SearchResults

router = APIRouter()
CANDIDATE_CAP_EXPLANATION_LIMIT = 20


class OptimizeScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=200)
    profile: AttendeeProfile
    filters: RecommendationFilters = Field(default_factory=RecommendationFilters)
    fixed_sessions: list[Session] = Field(default_factory=list)
    candidate_limit: int = Field(default=150, ge=1, le=500)
    event_start: date | None = None
    event_end: date | None = None

    @model_validator(mode="after")
    def valid_event_window(self) -> "OptimizeScheduleRequest":
        if self.event_start and self.event_end and self.event_end < self.event_start:
            raise ValueError("event_end must not precede event_start")
        return self


class ExplainedScheduleResponse(BaseModel):
    schedule: OptimizedSchedule
    explanation: ScheduleExplanation


@router.post("/schedule/optimize", response_model=OptimizedSchedule)
def optimize_local_schedule(
    request: OptimizeScheduleRequest,
    search_service: Annotated[SessionSearchService, Depends(get_search_service)],
) -> OptimizedSchedule:
    schedule, _ = _run_schedule(request, search_service)
    return schedule


@router.post("/schedule/explain", response_model=ExplainedScheduleResponse)
def explain_local_schedule(
    request: OptimizeScheduleRequest,
    search_service: Annotated[SessionSearchService, Depends(get_search_service)],
) -> ExplainedScheduleResponse:
    schedule, ranked = _run_schedule(
        request, search_service, overflow=CANDIDATE_CAP_EXPLANATION_LIMIT
    )
    explanation = explain_schedule(
        schedule,
        request.profile,
        capped_candidates=ranked.results[request.candidate_limit :],
        candidate_total=ranked.total,
        candidate_limit=request.candidate_limit,
    )
    return ExplainedScheduleResponse(schedule=schedule, explanation=explanation)


def _run_schedule(
    request: OptimizeScheduleRequest,
    search_service: SessionSearchService,
    *,
    overflow: int = 0,
) -> tuple[OptimizedSchedule, SearchResults]:
    ranked = search_service.search(
        request.query,
        request.filters.to_search_filters(),
        profile=request.profile,
        limit=request.candidate_limit + overflow,
    )
    try:
        schedule = optimize_schedule(
            ranked.results[: request.candidate_limit],
            request.profile,
            fixed_sessions=request.fixed_sessions,
            event_start=request.event_start,
            event_end=request.event_end,
        )
    except ScheduleConstraintError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return schedule, ranked
