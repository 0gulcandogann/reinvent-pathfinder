from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Session(BaseModel):
    """A normalized conference session, independent of AWS response keys."""

    model_config = ConfigDict(extra="forbid")

    id: str
    code: str | None = None
    title: str
    abstract: str | None = None
    session_type: str | None = None
    level: str | None = None
    tracks: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    speakers: list[str] = Field(default_factory=list)
    start_at: datetime | None = None
    end_at: datetime | None = None
    venue: str | None = None
    room: str | None = None
    reservable: bool = False
    availability: str | None = None
