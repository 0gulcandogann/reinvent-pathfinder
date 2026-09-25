"""Schema-validated parser boundary and credential-free deterministic parser."""

import re
from typing import Protocol

from pydantic import TypeAdapter, ValidationError

from app.agent.models import (
    AgentContext,
    ConfirmScheduleMutation,
    DiscardScheduleMutation,
    ExplainSchedule,
    ExplainSession,
    IntentFilters,
    OptimizeSchedule,
    PathfinderIntent,
    RecommendSessions,
    RefineProfile,
    ReoptimizeSchedule,
    SearchSessions,
    SetProfile,
    SuggestReplacement,
)
from app.models.profile import AttendeeProfile, TimeBlock

INTENT_ADAPTER = TypeAdapter(PathfinderIntent)
KNOWN_TOPICS = ("serverless", "security", "observability", "containers", "databases")
DAY_PATTERN = r"Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday"


class IntentParseError(ValueError):
    """Natural-language output could not be validated as a safe action."""


class IntentParser(Protocol):
    async def parse(self, message: str, context: AgentContext) -> PathfinderIntent: ...


class StructuredIntentProvider(Protocol):
    async def produce(
        self, message: str, context_hint: dict[str, object]
    ) -> object: ...


class SchemaIntentParser:
    """Optional LLM/provider bridge: only validated typed JSON passes through."""

    def __init__(self, provider: StructuredIntentProvider | None = None) -> None:
        self.provider = provider

    async def parse(self, message: str, context: AgentContext) -> PathfinderIntent:
        if self.provider is None:
            raise IntentParseError("Structured intent provider is not configured")
        # The hint contains no bearer tokens, raw schedule, or personal-time text.
        hint = {
            "interests": context.profile.interests,
            "has_latest_schedule": context.latest_schedule is not None,
            "pending_plan_id": context.pending_plan_id,
        }
        try:
            raw = await self.provider.produce(message, hint)
        except Exception as error:
            raise IntentParseError("Structured intent provider failed") from error
        try:
            return INTENT_ADAPTER.validate_python(raw)
        except (ValidationError, TypeError, ValueError) as error:
            raise IntentParseError(
                "Intent did not match a Pathfinder action schema"
            ) from error


class FakeIntentParser:
    """Small deterministic phrase parser plus scripted intents for offline use."""

    def __init__(self, scripted: dict[str, object] | None = None) -> None:
        self.scripted = scripted or {}

    async def parse(self, message: str, context: AgentContext) -> PathfinderIntent:
        phrase = message.strip()
        if phrase in self.scripted:
            try:
                return INTENT_ADAPTER.validate_python(self.scripted[phrase])
            except (ValidationError, TypeError, ValueError) as error:
                raise IntentParseError(
                    "Intent did not match a Pathfinder action schema"
                ) from error
        lower = phrase.casefold().rstrip(".!? ")
        if lower == "discard plan":
            return DiscardScheduleMutation()
        if lower.startswith("confirm plan "):
            return ConfirmScheduleMutation(
                plan_id=phrase[len("confirm plan ") :].strip()
            )
        if lower in {"do it", "go ahead", "looks good", "yeah", "confirm"}:
            return ConfirmScheduleMutation(plan_id=context.pending_plan_id)
        if lower.startswith("find "):
            query = re.sub(r"\bsessions?\b", "", phrase[5:], flags=re.I).strip()
            levels = []
            if "advanced" in query.casefold():
                query = re.sub(r"\badvanced\b", "", query, flags=re.I).strip()
                levels = ["300", "400"]
            return SearchSessions(query=query, filters=IntentFilters(levels=levels))
        if lower.startswith("recommend "):
            query = re.sub(r"\bsessions?\b", "", phrase[10:], flags=re.I).strip()
            return RecommendSessions(query=query)
        if lower.startswith("i'm ") or "interested in" in lower:
            interests = [topic for topic in KNOWN_TOPICS if topic in lower]
            levels = [level for level in ("100", "200", "300", "400") if level in lower]
            blocks = []
            if "tuesday afternoon free" in lower:
                blocks.append(TimeBlock(day="Tuesday", start="13:00", end="17:00"))
            return SetProfile(
                profile=AttendeeProfile(
                    interests=interests,
                    desired_levels=levels,
                    blocked_times=blocks,
                    minimize_venue_changes="venue changes" in lower,
                )
            )
        if "make " in lower and " less busy" in lower:
            match = re.search(rf"make ({DAY_PATTERN}) less busy", phrase, re.I)
            if match:
                return ReoptimizeSchedule(day=match.group(1))
        if lower.startswith("replace "):
            match = re.search(rf"({DAY_PATTERN})\s+(\d{{1,2}})\s*(am|pm)", phrase, re.I)
            hour = None
            day = None
            if match:
                day = match.group(1).title()
                hour = int(match.group(2)) % 12 + (
                    12 if match.group(3).lower() == "pm" else 0
                )
            topics = [topic for topic in KNOWN_TOPICS if topic in lower]
            return SuggestReplacement(
                reference_day=day,
                reference_hour=hour,
                desired_topics=topics,
                desired_levels=["300", "400"] if "advanced" in lower else [],
                query=" ".join(topics),
            )
        if "more advanced" in lower:
            return RefineProfile(desired_levels=["300", "400"], prioritize_depth=True)
        if "more security" in lower:
            return RefineProfile(add_interests=["security"])
        if "build my week" in lower or "optimize" in lower:
            topics = [topic for topic in KNOWN_TOPICS if topic in lower]
            return OptimizeSchedule(query=" ".join(topics or context.profile.interests))
        if "explain my schedule" in lower:
            return ExplainSchedule()
        if "explain this session" in lower:
            return ExplainSession(session_id=context.focused_session_id)
        raise IntentParseError("No supported Pathfinder intent was identified")
