"""Typed intent dispatch to the existing deterministic Pathfinder services."""

import hashlib
import json
import re
from datetime import date

from app.agent.models import (
    AgentContext,
    AgentResponse,
    ConfirmScheduleMutation,
    DiscardScheduleMutation,
    ExplainSchedule,
    ExplainSession,
    OptimizeSchedule,
    PlanScheduleMutation,
    RecommendSessions,
    RefineProfile,
    ReoptimizeSchedule,
    SearchSessions,
    SetProfile,
    SuggestReplacement,
)
from app.agent.parser import IntentParseError, IntentParser
from app.catalog.repository import SessionRepository
from app.catalog.search_service import SessionSearchService
from app.clients.events import EventsClient
from app.explain.service import explain_schedule
from app.models.profile import AttendeeProfile
from app.mutations.executor import MutationExecutionError, MutationExecutor
from app.mutations.models import Replacement, ScheduleMutationPlan
from app.mutations.planner import MutationPlanError, MutationPlanner
from app.optimizer.solve import ScheduleConstraintError
from app.optimizer.time import is_aware
from app.ranking.session_search import SearchFilters
from app.schedule.integration import ExistingSchedulePlanner, ScheduleIntegrationError

REPLACEMENT_WINDOW_HOURS = 2
REPLACEMENT_SEARCH_LIMIT = 30


class PathfinderAgent:
    """Interpret intent; delegate every score, constraint, and write to M2–M7."""

    def __init__(
        self,
        repository: SessionRepository,
        parser: IntentParser,
        events_client: EventsClient | None = None,
    ) -> None:
        self.repository = repository
        self.parser = parser
        self.events_client = events_client
        self.search = SessionSearchService(repository)
        self.schedule = ExistingSchedulePlanner(repository)
        self.mutations = MutationPlanner(repository)

    async def handle(self, message: str, context: AgentContext) -> AgentResponse:
        try:
            intent = await self.parser.parse(message, context)
        except IntentParseError as error:
            return AgentResponse(status="error", message=str(error))
        if isinstance(intent, ConfirmScheduleMutation) and not _explicit_confirmation(
            message, intent.plan_id
        ):
            return AgentResponse(
                intent=intent.kind,
                status="error",
                message="Explicit confirmation language is required for this plan.",
                pending_plan_id=context.pending_plan_id,
            )
        try:
            return await self._dispatch(intent, context)
        except (
            MutationPlanError,
            MutationExecutionError,
            ScheduleIntegrationError,
            ScheduleConstraintError,
            ValueError,
        ) as error:
            return AgentResponse(
                intent=intent.kind,
                status="error",
                message=str(error),
                pending_plan_id=context.pending_plan_id,
            )

    async def _dispatch(self, intent, context: AgentContext) -> AgentResponse:
        if isinstance(intent, SearchSessions):
            result = self.search.search(
                intent.query, intent.filters.to_search_filters(), limit=intent.limit
            )
            return AgentResponse(
                intent=intent.kind,
                status="ok",
                message=f"Found {result.total} matching sessions.",
                data=result.model_dump(mode="json"),
                invoked_service="SessionSearchService",
            )
        if isinstance(intent, RecommendSessions):
            result = self.search.search(
                intent.query,
                intent.filters.to_search_filters(),
                profile=context.profile,
                limit=intent.limit,
            )
            return AgentResponse(
                intent=intent.kind,
                status="ok",
                message=f"Ranked {result.total} sessions for your profile.",
                data=result.model_dump(mode="json"),
                invoked_service="SessionSearchService",
            )
        if isinstance(intent, OptimizeSchedule):
            return self._optimize(context, intent.query, intent.candidate_limit)
        if isinstance(intent, SetProfile):
            context.profile = intent.profile.model_copy(deep=True)
            self._clear_pending(context)
            if intent.optimize_after:
                query = " ".join(context.profile.interests)
                return self._optimize(
                    context, query, context.candidate_limit, intent.kind
                )
            return AgentResponse(
                intent=intent.kind,
                status="ok",
                message="Profile saved. No schedule changes were made.",
                data={"profile": context.profile.model_dump(mode="json")},
            )
        if isinstance(intent, RefineProfile):
            profile = context.profile.model_copy(deep=True)
            profile.interests = list(
                dict.fromkeys([*profile.interests, *intent.add_interests])
            )
            if intent.desired_levels is not None:
                profile.desired_levels = intent.desired_levels
            if intent.prioritize_depth is not None:
                profile.prioritize_depth = intent.prioritize_depth
            context.profile = AttendeeProfile.model_validate(profile.model_dump())
            self._clear_pending(context)
            if context.latest_schedule:
                return self._optimize(
                    context, context.last_query, context.candidate_limit, intent.kind
                )
            return AgentResponse(
                intent=intent.kind,
                status="ok",
                message="Profile preferences updated. No schedule changes were made.",
                data={"profile": context.profile.model_dump(mode="json")},
            )
        if isinstance(intent, ReoptimizeSchedule):
            return self._lighter_day(intent, context)
        if isinstance(intent, ExplainSchedule):
            if context.latest_schedule is None:
                return self._needs_context(intent.kind, "Optimize a schedule first.")
            explanation = explain_schedule(context.latest_schedule, context.profile)
            context.latest_explanation = explanation
            return AgentResponse(
                intent=intent.kind,
                status="ok",
                message="Here are the deterministic schedule reasons and insights.",
                data=explanation.model_dump(mode="json"),
                invoked_service="explain_schedule",
            )
        if isinstance(intent, ExplainSession):
            if context.latest_schedule is None:
                return self._needs_context(intent.kind, "Optimize a schedule first.")
            session_id = intent.session_id or context.focused_session_id
            explanation = explain_schedule(context.latest_schedule, context.profile)
            item = next(
                (
                    entry
                    for entry in explanation.sessions
                    if entry.session_id == session_id
                ),
                None,
            )
            if item is None:
                return self._needs_context(
                    intent.kind, "Select a scheduled session first."
                )
            context.focused_session_id = session_id
            return AgentResponse(
                intent=intent.kind,
                status="ok",
                message=f"Why {item.title} was selected.",
                data=item.model_dump(mode="json"),
                invoked_service="explain_schedule",
            )
        if isinstance(intent, SuggestReplacement):
            return self._suggest_replacement(intent, context)
        if isinstance(intent, PlanScheduleMutation):
            if context.latest_schedule is None:
                return self._needs_context(intent.kind, "Optimize a schedule first.")
            plan = self.mutations.build(
                context.current_schedule,
                context.latest_schedule,
                remove_session_ids=intent.remove_session_ids,
                replacements=intent.replacements,
            )
            return self._show_plan(context, plan, intent.kind)
        if isinstance(intent, ConfirmScheduleMutation):
            return await self._confirm(intent, context)
        if isinstance(intent, DiscardScheduleMutation):
            self._clear_pending(context)
            return AgentResponse(
                intent=intent.kind,
                status="ok",
                message="Pending plan discarded. No schedule changes were made.",
            )
        raise IntentParseError("Unsupported Pathfinder intent")

    def _optimize(
        self,
        context: AgentContext,
        query: str,
        candidate_limit: int,
        kind: str = "optimize_schedule",
    ) -> AgentResponse:
        result = self.schedule.plan(
            context.current_schedule,
            context.profile,
            query=query,
            candidate_limit=candidate_limit,
            daily_limits={
                date.fromisoformat(key): value
                for key, value in context.daily_limits.items()
            },
        )
        context.latest_schedule = result.schedule
        context.latest_explanation = result.explanation
        context.last_query = query
        context.candidate_limit = candidate_limit
        self._clear_pending(context)
        return AgentResponse(
            intent=kind,
            status="ok",
            message=(
                f"Optimized {len(result.schedule.selected_sessions)} sessions with "
                f"utility {result.schedule.score:g}. No AWS changes were made."
            ),
            data=result.model_dump(mode="json"),
            invoked_service="ExistingSchedulePlanner",
        )

    def _lighter_day(
        self, intent: ReoptimizeSchedule, context: AgentContext
    ) -> AgentResponse:
        if context.latest_schedule is None:
            return self._needs_context(intent.kind, "Optimize a schedule first.")
        matches = [
            (date.fromisoformat(day), count)
            for day, count in context.latest_schedule.sessions_per_day.items()
            if date.fromisoformat(day).strftime("%A") == intent.day
        ]
        if len(matches) != 1:
            return self._needs_context(
                intent.kind, "Name one day present in the current itinerary."
            )
        day, count = matches[0]
        fixed_count = sum(
            item.fixed and item.event_local_start_at.date() == day
            for item in context.latest_schedule.selected_sessions
        )
        limit = max(1, fixed_count, count - intent.lighter_by)
        if limit >= count:
            return AgentResponse(
                intent=intent.kind,
                status="ok",
                message=f"{intent.day} cannot be lighter while fixed sessions remain.",
                data={"day": day.isoformat(), "sessions": count},
            )
        context.daily_limits[day.isoformat()] = limit
        response = self._optimize(
            context, context.last_query, context.candidate_limit, intent.kind
        )
        response.message = (
            f"{intent.day} now has at most {limit} sessions. No AWS changes were made."
        )
        return response

    def _suggest_replacement(
        self, intent: SuggestReplacement, context: AgentContext
    ) -> AgentResponse:
        if context.latest_schedule is None:
            return self._needs_context(intent.kind, "Optimize a schedule first.")
        current_id = self._resolve_session_reference(intent, context)
        if current_id is None:
            return self._needs_context(
                intent.kind, "The session reference is missing or ambiguous."
            )
        if current_id not in context.current_schedule.reserved_session_ids:
            return self._needs_context(
                intent.kind, "Replacement requires an existing reserved session."
            )
        old = self.repository.get(current_id)
        if old is None or old.start_at is None or old.end_at is None:
            return self._needs_context(
                intent.kind, "Current session is unavailable locally."
            )
        query = intent.query or " ".join(intent.desired_topics)
        filters = SearchFilters(levels=tuple(intent.desired_levels))
        ranked = self.search.search(
            query,
            filters,
            profile=context.profile,
            limit=REPLACEMENT_SEARCH_LIMIT,
        )
        candidates = [
            hit
            for hit in ranked.results
            if hit.session.id != current_id
            and hit.session.start_at is not None
            and hit.session.end_at is not None
            and is_aware(hit.session.start_at) == is_aware(old.start_at)
            and hit.session.start_at.date() == old.start_at.date()
            and abs((hit.session.start_at - old.start_at).total_seconds())
            <= REPLACEMENT_WINDOW_HOURS * 3600
        ]
        # Prefer an option that can be reserved before releasing the old seat.
        candidates.sort(
            key=lambda hit: (
                hit.session.start_at < old.end_at and old.start_at < hit.session.end_at,
                -hit.score,
                hit.session.id,
            )
        )
        reduced = context.current_schedule.model_copy(deep=True)
        reduced.reserved_session_ids.remove(current_id)
        refined = context.profile.model_copy(deep=True)
        if intent.desired_topics:
            refined.preferred_topics = list(
                dict.fromkeys([*refined.preferred_topics, *intent.desired_topics])
            )
        if intent.desired_levels:
            refined.desired_levels = intent.desired_levels
        for hit in candidates:
            result = self.schedule.plan(
                reduced,
                refined,
                query=query,
                filters=filters,
                allowed_candidate_ids={hit.session.id},
                daily_limits={
                    date.fromisoformat(key): value
                    for key, value in context.daily_limits.items()
                },
            )
            if hit.session.id not in result.proposed_addition_ids:
                continue
            plan = self.mutations.build(
                context.current_schedule,
                result.schedule,
                replacements=[
                    Replacement(
                        old_session_id=current_id, new_session_id=hit.session.id
                    )
                ],
            )
            context.latest_schedule = result.schedule
            context.latest_explanation = result.explanation
            return self._show_plan(context, plan, intent.kind)
        return self._needs_context(intent.kind, "No schedulable replacement was found.")

    def _resolve_session_reference(
        self, intent: SuggestReplacement, context: AgentContext
    ) -> str | None:
        if intent.current_session_id:
            return intent.current_session_id
        matches = [
            item.hit.session.id
            for item in context.latest_schedule.selected_sessions
            if intent.reference_day
            and intent.reference_hour is not None
            and item.event_local_start_at is not None
            and item.event_local_start_at.strftime("%A") == intent.reference_day
            and item.event_local_start_at.hour == intent.reference_hour
        ]
        if len(matches) == 1:
            return matches[0]
        if intent.reference_day is None and intent.reference_hour is None:
            return context.focused_session_id
        return None

    def _show_plan(
        self, context: AgentContext, plan: ScheduleMutationPlan, kind: str
    ) -> AgentResponse:
        context.plan_version += 1
        plan_id = _plan_identity(plan, context.plan_version)
        context.pending_plan = plan
        context.pending_plan_id = plan_id
        return AgentResponse(
            intent=kind,
            status="confirmation_required",
            message=(
                f"Proposed {len(plan.additions)} additions and "
                f"{len(plan.removals)} removals. No AWS changes were made."
            ),
            data={"plan": plan.model_dump(mode="json")},
            invoked_service="MutationPlanner",
            requires_confirmation=True,
            pending_plan_id=plan_id,
        )

    async def _confirm(
        self, intent: ConfirmScheduleMutation, context: AgentContext
    ) -> AgentResponse:
        if context.pending_plan is None or context.pending_plan_id is None:
            return self._needs_context(
                intent.kind, "There is no pending mutation plan."
            )
        if intent.plan_id != context.pending_plan_id:
            return self._needs_context(
                intent.kind, "Confirmation does not match the pending plan."
            )
        if _plan_identity(context.pending_plan, context.plan_version) != intent.plan_id:
            self._clear_pending(context)
            return self._needs_context(
                intent.kind, "Pending plan changed after review; create a new plan."
            )
        result = await MutationExecutor(self.events_client).execute(
            context.pending_plan, confirmed=True
        )
        self._clear_pending(context)
        if result.verified_schedule is not None:
            context.current_schedule = result.verified_schedule
        context.latest_schedule = None
        context.latest_explanation = None
        return AgentResponse(
            intent=intent.kind,
            status="ok" if result.status == "completed" else "error",
            message=(
                f"Mutation result: {result.status}. Final state was read with "
                "GetSchedule where available."
            ),
            data=result.model_dump(mode="json"),
            invoked_service="MutationExecutor",
        )

    @staticmethod
    def _clear_pending(context: AgentContext) -> None:
        context.pending_plan = None
        context.pending_plan_id = None

    @staticmethod
    def _needs_context(kind: str, message: str) -> AgentResponse:
        return AgentResponse(intent=kind, status="needs_context", message=message)


def _explicit_confirmation(message: str, plan_id: str | None) -> bool:
    phrase = message.strip().casefold().rstrip(".!? ")
    if phrase in {"do it", "go ahead", "looks good", "yeah", "confirm"}:
        return True
    return bool(
        plan_id
        and re.fullmatch(rf"confirm plan {re.escape(plan_id.casefold())}", phrase)
    )


def _plan_identity(plan: ScheduleMutationPlan, version: int) -> str:
    canonical = json.dumps(plan.model_dump(mode="json"), sort_keys=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{version}-{digest}"
