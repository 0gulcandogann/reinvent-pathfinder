"""Pathfinder's normalized attendee schedule, independent of AWS JSON."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PersonalTime(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str | None = None
    location: str | None = None
    start_at: datetime
    end_at: datetime

    @model_validator(mode="after")
    def valid_interval(self) -> "PersonalTime":
        if self.start_at.utcoffset() is None or self.end_at.utcoffset() is None:
            raise ValueError("personal time datetimes must be timezone aware")
        if self.end_at <= self.start_at:
            raise ValueError("personal time must end after it starts")
        return self


class AttendeeSchedule(BaseModel):
    """Reserved IDs are commitments; favorite IDs express interest only."""

    model_config = ConfigDict(extra="forbid")

    reserved_session_ids: list[str] = Field(default_factory=list)
    favorite_session_ids: list[str] = Field(default_factory=list)
    personal_time: list[PersonalTime] = Field(default_factory=list)

    @field_validator("reserved_session_ids", "favorite_session_ids")
    @classmethod
    def valid_session_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("schedule session IDs must be nonempty")
        return list(dict.fromkeys(normalized))
