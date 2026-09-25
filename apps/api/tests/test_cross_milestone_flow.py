"""Offline regression for the main read, plan, confirm, verify chain."""

import asyncio
import json
from pathlib import Path

from app.catalog.sqlite import SqliteSessionRepository
from app.catalog.sync import sync_catalog
from app.clients.fake import FakeEventsClient
from app.models.profile import AttendeeProfile
from app.mutations.executor import MutationExecutor
from app.mutations.planner import MutationPlanner
from app.schedule.integration import ExistingSchedulePlanner
from app.schedule.normalize import normalize_schedule

FIXTURES = Path(__file__).resolve().parents[3] / "data" / "fixtures"


def test_catalog_to_verified_schedule_flow(tmp_path) -> None:
    raw_catalog = json.loads(
        (FIXTURES / "existing_schedule_catalog.json").read_text(encoding="utf-8")
    )
    raw_schedule = json.loads(
        (FIXTURES / "aws_get_schedule.json").read_text(encoding="utf-8")
    )
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    asyncio.run(sync_catalog(FakeEventsClient(raw_catalog), repository))
    current = normalize_schedule(raw_schedule)
    profile = AttendeeProfile(
        interests=["serverless", "security", "observability"],
        preferred_services=["AWS Lambda"],
        desired_levels=["300", "400"],
        learning_goals=["observability"],
        max_sessions_per_day=5,
    )
    integrated = ExistingSchedulePlanner(repository).plan(current, profile)
    assert set(current.reserved_session_ids) <= {
        item.hit.session.id for item in integrated.schedule.selected_sessions
    }
    assert integrated.explanation.sessions
    assert integrated.proposed_addition_ids
    plan = MutationPlanner(repository).build(current, integrated.schedule)
    assert [item.session_id for item in plan.additions] == sorted(
        integrated.proposed_addition_ids
    )
    fake = FakeEventsClient(schedule=raw_schedule)
    unconfirmed = asyncio.run(MutationExecutor(fake).execute(plan, confirmed=False))
    assert unconfirmed.status == "confirmation_required"
    assert fake.write_calls == []
    confirmed = asyncio.run(MutationExecutor(fake).execute(plan, confirmed=True))
    assert confirmed.status == "completed"
    assert set(confirmed.reservation_result.succeeded) == set(
        integrated.proposed_addition_ids
    )
    assert set(confirmed.verified_schedule.reserved_session_ids) == set(
        current.reserved_session_ids + integrated.proposed_addition_ids
    )
    assert confirmed.verified_schedule.personal_time == current.personal_time
    assert (
        confirmed.verified_schedule.favorite_session_ids == current.favorite_session_ids
    )
