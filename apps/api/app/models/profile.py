"""Attendee preferences, independent of transport and search storage."""

from datetime import date, time

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
WEEKDAYS = {name.casefold() for name in WEEKDAY_NAMES}


class TimeBlock(BaseModel):
    """An event-local blocked interval, by weekday or ISO calendar date."""

    model_config = ConfigDict(extra="forbid")

    day: str
    start: time
    end: time

    @field_validator("day")
    @classmethod
    def valid_day(cls, value: str) -> str:
        day = value.strip()
        if day.casefold() not in WEEKDAYS:
            try:
                date.fromisoformat(day)
            except ValueError as error:
                raise ValueError("day must be a weekday or ISO date") from error
        return day

    @model_validator(mode="after")
    def end_after_start(self) -> "TimeBlock":
        if self.start.tzinfo is not None or self.end.tzinfo is not None:
            raise ValueError("blocked times must be local clock times without offsets")
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class AttendeeProfile(BaseModel):
    """M3 uses preferences and depth; M4 uses time, load, and venue fields."""

    model_config = ConfigDict(extra="forbid")

    interests: list[str] = Field(default_factory=list)
    preferred_services: list[str] = Field(default_factory=list)
    preferred_topics: list[str] = Field(default_factory=list)
    desired_levels: list[str] = Field(default_factory=list)
    avoided_levels: list[str] = Field(default_factory=list)
    preferred_session_types: list[str] = Field(default_factory=list)
    learning_goals: list[str] = Field(default_factory=list)
    prioritize_depth: bool = False

    # M4 scheduling fields; ignored by M3 ranking.
    blocked_times: list[TimeBlock] = Field(default_factory=list)
    max_sessions_per_day: int | None = Field(default=None, ge=1)
    minimize_venue_changes: bool = False
    diversity_weight: float = Field(default=0.0, ge=0.0, le=1.0)
