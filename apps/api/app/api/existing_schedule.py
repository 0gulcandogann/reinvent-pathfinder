"""Offline HTTP adapter for existing attendee schedule optimization."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.search import RecommendationFilters
from app.catalog.sqlite import SqliteSessionRepository, catalog_db_path
from app.models.profile import AttendeeProfile
from app.optimizer.solve import ScheduleConstraintError
from app.schedule.integration import (
    DEFAULT_EVENT_TIMEZONE,
    ExistingSchedulePlanner,
    IntegratedSchedule,
    ScheduleIntegrationError,
)
from app.schedule.models import AttendeeSchedule

router = APIRouter()


class OptimizeExistingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=200)
    profile: AttendeeProfile
    existing_schedule: AttendeeSchedule
    filters: RecommendationFilters = Field(default_factory=RecommendationFilters)
    candidate_limit: int = Field(default=150, ge=1, le=500)
    event_timezone: str = DEFAULT_EVENT_TIMEZONE
    event_start: date | None = None
    event_end: date | None = None

    @model_validator(mode="after")
    def valid_event_window(self) -> "OptimizeExistingRequest":
        if self.event_start and self.event_end and self.event_end < self.event_start:
            raise ValueError("event_end must not precede event_start")
        return self


def get_existing_schedule_planner() -> ExistingSchedulePlanner:
    return ExistingSchedulePlanner(SqliteSessionRepository(catalog_db_path()))


@router.post("/schedule/optimize-existing", response_model=IntegratedSchedule)
def optimize_existing_schedule(
    request: OptimizeExistingRequest,
    planner: Annotated[ExistingSchedulePlanner, Depends(get_existing_schedule_planner)],
) -> IntegratedSchedule:
    try:
        return planner.plan(
            request.existing_schedule,
            request.profile,
            query=request.query,
            filters=request.filters.to_search_filters(),
            candidate_limit=request.candidate_limit,
            event_timezone=request.event_timezone,
            event_start=request.event_start,
            event_end=request.event_end,
        )
    except (ScheduleIntegrationError, ScheduleConstraintError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
