import asyncio
import json
from pathlib import Path

import pytest

from app.agent.models import AgentContext
from app.agent.parser import (
    FakeIntentParser,
    IntentParseError,
    SchemaIntentParser,
)
from app.agent.service import PathfinderAgent
from app.catalog.sqlite import SqliteSessionRepository
from app.catalog.sync import sync_catalog
from app.clients.fake import FakeEventsClient
from app.schedule.normalize import normalize_schedule

CATALOG = (
    Path(__file__).resolve().parents[3] / "data" / "fixtures" / "agent_catalog.json"
)


def _setup(tmp_path, parser=None):
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    schedule = {
        "schedule": {"reserved": ["sec340"], "favorites": [], "personalTime": []}
    }
    fake = FakeEventsClient(catalog, schedule=schedule)
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    asyncio.run(sync_catalog(fake, repository))
    agent = PathfinderAgent(repository, parser or FakeIntentParser(), fake)
    context = AgentContext(current_schedule=normalize_schedule(schedule))
    return agent, context, fake


def _run(agent, message, context):
    return asyncio.run(agent.handle(message, context))


class _Provider:
    def __init__(self, output):
        self.output = output
        self.hint = None

    async def produce(self, _message, context_hint):
        self.hint = context_hint
        return self.output


def test_schema_parser_validates_structured_intents_and_excludes_schedule_from_hint():
    provider = _Provider({"kind": "search_sessions", "query": "AWS Lambda"})
    context = AgentContext()
    result = asyncio.run(SchemaIntentParser(provider).parse("search", context))
    assert result.kind == "search_sessions"
    assert result.query == "AWS Lambda"
    assert "current_schedule" not in provider.hint
    assert "access_token" not in provider.hint


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "unknown_action"},
        {"kind": "search_sessions", "query": ""},
        {"kind": "set_profile", "profile": {"max_sessions_per_day": 0}},
        {"kind": "confirm_schedule_mutation", "plan_id": "x", "method": "DELETE"},
    ],
)
def test_invalid_unknown_or_malformed_structured_intent_is_rejected(payload) -> None:
    with pytest.raises(IntentParseError):
        asyncio.run(
            SchemaIntentParser(_Provider(payload)).parse("anything", AgentContext())
        )


def test_missing_llm_configuration_is_safe() -> None:
    with pytest.raises(IntentParseError, match="not configured"):
        asyncio.run(SchemaIntentParser().parse("anything", AgentContext()))


def test_provider_error_is_redacted() -> None:
    class BrokenProvider:
        async def produce(self, _message, _hint):
            raise RuntimeError("private-token")

    with pytest.raises(IntentParseError) as error:
        asyncio.run(SchemaIntentParser(BrokenProvider()).parse("x", AgentContext()))
    assert "private-token" not in str(error.value)


def test_search_and_recommend_dispatch_to_local_search(tmp_path) -> None:
    parser = FakeIntentParser(
        {
            "search": {"kind": "search_sessions", "query": "Lambda"},
            "recommend": {"kind": "recommend_sessions", "query": "security"},
        }
    )
    agent, context, fake = _setup(tmp_path, parser)
    search = _run(agent, "search", context)
    recommend = _run(agent, "recommend", context)
    assert search.invoked_service == "SessionSearchService"
    assert search.data["total"] >= 1
    assert recommend.invoked_service == "SessionSearchService"
    assert fake.write_calls == []


def test_natural_language_advanced_lambda_becomes_filtered_search(tmp_path) -> None:
    agent, context, _ = _setup(tmp_path)
    intent = asyncio.run(agent.parser.parse("Find advanced Lambda sessions", context))
    assert intent.kind == "search_sessions"
    assert intent.query == "Lambda"
    assert intent.filters.levels == ["300", "400"]
    result = _run(agent, "Find advanced Lambda sessions", context)
    assert result.invoked_service == "SessionSearchService"
    assert result.data["total"] >= 1


def test_profile_creation_optimization_and_explanation_use_existing_services(
    tmp_path,
) -> None:
    agent, context, fake = _setup(tmp_path)
    profile = _run(
        agent,
        "I'm interested in serverless, security and observability. "
        "Prefer Level 300 and 400. Keep Tuesday afternoon free.",
        context,
    )
    assert profile.intent == "set_profile"
    assert profile.invoked_service == "ExistingSchedulePlanner"
    assert context.profile.desired_levels == ["300", "400"]
    assert context.profile.blocked_times[0].day == "Tuesday"
    assert context.latest_schedule is not None
    assert "tueblocked" not in [
        item.hit.session.id for item in context.latest_schedule.selected_sessions
    ]
    explanation = _run(agent, "explain my schedule", context)
    assert explanation.invoked_service == "explain_schedule"
    assert explanation.data["metrics"]["fixed_session_count"] == 1
    assert fake.write_calls == []


def test_make_wednesday_lighter_uses_day_specific_optimizer_limit(tmp_path) -> None:
    agent, context, fake = _setup(tmp_path)
    _run(agent, "I'm interested in serverless, security and observability.", context)
    before = context.latest_schedule.sessions_per_day["2026-12-02"]
    result = _run(agent, "Make Wednesday less busy.", context)
    after = context.latest_schedule.sessions_per_day["2026-12-02"]
    assert result.intent == "reoptimize_schedule"
    assert result.invoked_service == "ExistingSchedulePlanner"
    assert after == before - 1
    assert context.daily_limits["2026-12-02"] == after
    assert context.latest_schedule.sessions_per_day["2026-11-30"] == 2
    assert fake.write_calls == []


def test_depth_and_topic_refinement_rerank_without_writes(tmp_path) -> None:
    agent, context, fake = _setup(tmp_path)
    _run(agent, "I'm interested in serverless and observability.", context)
    advanced = _run(agent, "Give me more advanced sessions.", context)
    security = _run(agent, "I want more security content.", context)
    assert advanced.intent == "refine_profile"
    assert context.profile.prioritize_depth is True
    assert context.profile.desired_levels == ["300", "400"]
    assert "security" in context.profile.interests
    assert security.invoked_service == "ExistingSchedulePlanner"
    assert fake.write_calls == []


def test_do_it_without_pending_plan_performs_zero_writes(tmp_path) -> None:
    agent, context, fake = _setup(tmp_path)
    result = _run(agent, "Do it.", context)
    assert result.status == "needs_context"
    assert fake.write_calls == []
    assert fake.get_schedule_calls == 0


def test_replacement_plan_confirmation_and_get_schedule_verification(tmp_path) -> None:
    agent, context, fake = _setup(tmp_path)
    _run(agent, "I'm interested in serverless, security and observability.", context)
    replacement = _run(
        agent,
        "Replace my Wednesday 2 PM session with something more advanced "
        "about containers.",
        context,
    )
    assert replacement.intent == "suggest_replacement"
    assert replacement.requires_confirmation is True
    assert replacement.pending_plan_id == context.pending_plan_id
    assert [item.session_id for item in context.pending_plan.additions] == ["con410"]
    assert [item.session_id for item in context.pending_plan.removals] == ["sec340"]
    assert fake.write_calls == []
    confirmed = _run(agent, "Do it.", context)
    assert confirmed.intent == "confirm_schedule_mutation"
    assert confirmed.invoked_service == "MutationExecutor"
    assert confirmed.data["status"] == "completed"
    assert confirmed.data["verified_schedule"]["reserved_session_ids"] == ["con410"]
    assert fake.write_calls == [("reserve", ["con410"]), ("cancel", "sec340")]
    assert context.pending_plan is None


def test_confirmation_of_wrong_or_stale_plan_performs_no_writes(tmp_path) -> None:
    parser = FakeIntentParser(
        {"confirm": {"kind": "confirm_schedule_mutation", "plan_id": "other-plan"}}
    )
    agent, context, fake = _setup(tmp_path, parser)
    _run(agent, "I'm interested in security and containers.", context)
    _run(
        agent,
        "Replace my Wednesday 2 PM session with advanced containers.",
        context,
    )
    mismatch = _run(agent, "confirm", context)
    assert mismatch.status == "needs_context"
    assert fake.write_calls == []

    fake.schedule["schedule"]["reserved"].append("external-change")
    stale = _run(agent, "Do it.", context)
    assert stale.data["status"] == "stale_plan"
    assert fake.write_calls == []


def test_schema_valid_confirmation_cannot_write_for_unrelated_message(tmp_path) -> None:
    agent, context, fake = _setup(tmp_path)
    _run(agent, "I'm interested in security and containers.", context)
    _run(
        agent,
        "Replace my Wednesday 2 PM session with advanced containers.",
        context,
    )
    agent.parser = SchemaIntentParser(
        _Provider(
            {
                "kind": "confirm_schedule_mutation",
                "plan_id": context.pending_plan_id,
            }
        )
    )
    result = _run(agent, "Explain my schedule", context)
    assert result.status == "error"
    assert context.pending_plan is not None
    assert fake.write_calls == []


def test_pending_plan_digest_detects_changes_after_review(tmp_path) -> None:
    agent, context, fake = _setup(tmp_path)
    _run(agent, "I'm interested in security and containers.", context)
    _run(
        agent,
        "Replace my Wednesday 2 PM session with advanced containers.",
        context,
    )
    context.pending_plan.additions[0].session_id = "other"
    result = _run(agent, "Do it.", context)
    assert result.status == "needs_context"
    assert context.pending_plan is None
    assert fake.write_calls == []


def test_ambiguous_contextual_reference_never_creates_plan(tmp_path) -> None:
    agent, context, fake = _setup(tmp_path)
    _run(agent, "I'm interested in security and containers.", context)
    result = _run(
        agent,
        "Replace my Wednesday 3 PM session with advanced containers.",
        context,
    )
    assert result.status == "needs_context"
    assert context.pending_plan is None
    assert fake.write_calls == []
