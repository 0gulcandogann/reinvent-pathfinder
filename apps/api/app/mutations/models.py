"""Typed mutation intent and per-session operation outcomes."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schedule.models import AttendeeSchedule


class MutationAction(BaseModel):
    session_id: str
    title: str | None = None
    action: Literal["reserve", "cancel", "keep"]
    reason: str
    provenance: Literal["existing_reserved", "pathfinder_selected"]
    conflicts_with: list[str] = Field(default_factory=list)


class Replacement(BaseModel):
    old_session_id: str
    new_session_id: str
    reason: str = "explicit_replacement"


class ScheduleMutationPlan(BaseModel):
    baseline_schedule: AttendeeSchedule
    additions: list[MutationAction] = Field(default_factory=list)
    removals: list[MutationAction] = Field(default_factory=list)
    unchanged: list[MutationAction] = Field(default_factory=list)
    replacements: list[Replacement] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class OperationFailure(BaseModel):
    session_id: str
    code: str
    message: str
    conflicts_with: list[str] = Field(default_factory=list)


class ReservationResult(BaseModel):
    succeeded: list[str] = Field(default_factory=list)
    failed: list[OperationFailure] = Field(default_factory=list)


class CancellationResult(BaseModel):
    succeeded: list[str] = Field(default_factory=list)
    failed: list[OperationFailure] = Field(default_factory=list)


class VerificationFailure(BaseModel):
    kind: Literal[
        "api_operation_failed",
        "reported_success_missing",
        "cancellation_still_present",
        "unchanged_missing",
        "get_schedule_failed",
        "stale_plan",
        "replacement_deferred",
    ]
    session_id: str | None = None
    message: str


class MutationExecutionResult(BaseModel):
    status: Literal[
        "confirmation_required",
        "stale_plan",
        "completed",
        "partially_completed",
        "verification_failed",
    ]
    reservation_result: ReservationResult = Field(default_factory=ReservationResult)
    cancellation_result: CancellationResult = Field(default_factory=CancellationResult)
    verified_schedule: AttendeeSchedule | None = None
    verification_failures: list[VerificationFailure] = Field(default_factory=list)
    skipped_actions: list[MutationAction] = Field(default_factory=list)
