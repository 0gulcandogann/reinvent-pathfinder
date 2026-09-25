"""Agent intent and conversation state; no transport or LLM types."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.explain.models import ScheduleExplanation
from app.models.profile import WEEKDAYS, AttendeeProfile
from app.mutations.models import Replacement, ScheduleMutationPlan
from app.optimizer.models import OptimizedSchedule
from app.ranking.session_search import SearchFilters
from app.schedule.models import AttendeeSchedule


class IntentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntentFilters(IntentModel):
    levels: list[str] = Field(default_factory=list)
    session_types: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    tracks: list[str] = Field(default_factory=list)

    def to_search_filters(self) -> SearchFilters:
        return SearchFilters(
            levels=tuple(self.levels),
            session_types=tuple(self.session_types),
            services=tuple(self.services),
            topics=tuple(self.topics),
            tracks=tuple(self.tracks),
        )


class SearchSessions(IntentModel):
    kind: Literal["search_sessions"] = "search_sessions"
    query: str = Field(min_length=1, max_length=200)
    filters: IntentFilters = Field(default_factory=IntentFilters)
    limit: int = Field(default=10, ge=1, le=100)


class RecommendSessions(IntentModel):
    kind: Literal["recommend_sessions"] = "recommend_sessions"
    query: str = Field(default="", max_length=200)
    filters: IntentFilters = Field(default_factory=IntentFilters)
    limit: int = Field(default=10, ge=1, le=100)


class OptimizeSchedule(IntentModel):
    kind: Literal["optimize_schedule"] = "optimize_schedule"
    query: str = Field(default="", max_length=200)
    candidate_limit: int = Field(default=150, ge=1, le=500)


class ExplainSession(IntentModel):
    kind: Literal["explain_session"] = "explain_session"
    session_id: str | None = None


class ExplainSchedule(IntentModel):
    kind: Literal["explain_schedule"] = "explain_schedule"


class SuggestReplacement(IntentModel):
    kind: Literal["suggest_replacement"] = "suggest_replacement"
    current_session_id: str | None = None
    reference_day: str | None = None
    reference_hour: int | None = Field(default=None, ge=0, le=23)
    desired_topics: list[str] = Field(default_factory=list)
    desired_levels: list[str] = Field(default_factory=list)
    query: str = ""

    @field_validator("reference_day")
    @classmethod
    def valid_day(cls, value: str | None) -> str | None:
        if value is not None and value.casefold() not in WEEKDAYS:
            raise ValueError("reference_day must be a weekday")
        return value


class PlanScheduleMutation(IntentModel):
    kind: Literal["plan_schedule_mutation"] = "plan_schedule_mutation"
    remove_session_ids: list[str] = Field(default_factory=list)
    replacements: list[Replacement] = Field(default_factory=list)


class ConfirmScheduleMutation(IntentModel):
    kind: Literal["confirm_schedule_mutation"] = "confirm_schedule_mutation"
    plan_id: str | None = None


class DiscardScheduleMutation(IntentModel):
    kind: Literal["discard_schedule_mutation"] = "discard_schedule_mutation"


class SetProfile(IntentModel):
    kind: Literal["set_profile"] = "set_profile"
    profile: AttendeeProfile
    optimize_after: bool = True


class RefineProfile(IntentModel):
    kind: Literal["refine_profile"] = "refine_profile"
    add_interests: list[str] = Field(default_factory=list)
    desired_levels: list[str] | None = None
    prioritize_depth: bool | None = None


class ReoptimizeSchedule(IntentModel):
    kind: Literal["reoptimize_schedule"] = "reoptimize_schedule"
    day: str
    lighter_by: int = Field(default=1, ge=1, le=10)

    @field_validator("day")
    @classmethod
    def valid_day(cls, value: str) -> str:
        if value.casefold() not in WEEKDAYS:
            raise ValueError("day must be a weekday")
        return value.title()


PathfinderIntent = Annotated[
    SearchSessions
    | RecommendSessions
    | OptimizeSchedule
    | ExplainSession
    | ExplainSchedule
    | SuggestReplacement
    | PlanScheduleMutation
    | ConfirmScheduleMutation
    | DiscardScheduleMutation
    | SetProfile
    | RefineProfile
    | ReoptimizeSchedule,
    Field(discriminator="kind"),
]


class AgentContext(BaseModel):
    profile: AttendeeProfile = Field(default_factory=AttendeeProfile)
    current_schedule: AttendeeSchedule = Field(default_factory=AttendeeSchedule)
    latest_schedule: OptimizedSchedule | None = None
    latest_explanation: ScheduleExplanation | None = None
    last_query: str = ""
    candidate_limit: int = 150
    daily_limits: dict[str, int] = Field(default_factory=dict)
    focused_session_id: str | None = None
    pending_plan: ScheduleMutationPlan | None = None
    pending_plan_id: str | None = None
    plan_version: int = 0


class AgentResponse(BaseModel):
    intent: str | None = None
    status: Literal["ok", "error", "needs_context", "confirmation_required"]
    message: str
    data: dict[str, object] = Field(default_factory=dict)
    invoked_service: str | None = None
    requires_confirmation: bool = False
    pending_plan_id: str | None = None
