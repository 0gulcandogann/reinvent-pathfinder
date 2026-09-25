import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.catalog.sqlite import SqliteSessionRepository
from app.catalog.sync import sync_catalog
from app.clients.fake import FakeEventsClient
from app.models.profile import AttendeeProfile
from app.models.session import Session
from app.schedule.integration import ExistingSchedulePlanner, ScheduleIntegrationError
from app.schedule.models import AttendeeSchedule, PersonalTime
from app.schedule.normalize import normalize_schedule

ROOT = Path(__file__).resolve().parents[3]


def _fixture_planner(tmp_path):
    catalog = json.loads(
        (ROOT / "data" / "fixtures" / "existing_schedule_catalog.json").read_text(
            encoding="utf-8"
        )
    )
    raw_schedule = json.loads(
        (ROOT / "data" / "fixtures" / "aws_get_schedule.json").read_text(
            encoding="utf-8"
        )
    )
    fake = FakeEventsClient(catalog, schedule=raw_schedule)
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    asyncio.run(sync_catalog(fake, repository))
    attendee_schedule = normalize_schedule(asyncio.run(fake.get_schedule()))
    return ExistingSchedulePlanner(repository), attendee_schedule


def test_existing_schedule_is_preserved_and_gaps_are_filled(tmp_path) -> None:
    planner, attendee_schedule = _fixture_planner(tmp_path)
    profile = AttendeeProfile(
        interests=["serverless", "security", "observability"],
        preferred_services=["AWS Lambda"],
        desired_levels=["300", "400"],
        max_sessions_per_day=5,
        minimize_venue_changes=True,
        prioritize_depth=True,
    )
    original_profile = profile.model_dump(mode="json")
    original_schedule = attendee_schedule.model_dump(mode="json")
    plan = planner.plan(
        attendee_schedule,
        profile,
        query="serverless security observability",
    )
    assert plan.already_reserved_ids == ["sec310", "svs320"]
    assert set(plan.proposed_addition_ids) == {
        "cop330",
        "con410",
        "svst1",
        "sect2",
        "obst4",
    }
    assert plan.schedule.constraints.fixed_session_count == 2
    assert plan.schedule.venue_transitions == 1
    assert plan.schedule.venue_penalty == 2
    assert profile.model_dump(mode="json") == original_profile
    assert attendee_schedule.model_dump(mode="json") == original_schedule


def test_fixed_and_personal_conflicts_rejected_and_favorites_remain_metadata(
    tmp_path,
) -> None:
    planner, attendee_schedule = _fixture_planner(tmp_path)
    plan = planner.plan(
        attendee_schedule,
        AttendeeProfile(interests=["serverless", "security", "observability"]),
        query="serverless security observability",
    )
    rejected = {
        item.hit.session.id: item.reason for item in plan.schedule.rejected_sessions
    }
    assert rejected["sec399"] == "fixed_session_conflict"
    assert rejected["fav320"] == "fixed_session_conflict"
    assert rejected["blkt3"] == "blocked_time_conflict"
    assert plan.schedule.constraints.blocked_time_count == 1
    assert plan.personal_time_items[0].source == "personal_time"
    assert plan.personal_time_items[0].event_local_start_at.hour == 13
    assert plan.personal_time_items[0].event_local_end_at.hour == 17
    assert plan.favorite_session_ids == ["cop330", "fav320", "svst1"]
    by_id = {item.session.id: item for item in plan.session_items}
    assert by_id["sec310"].source == "existing_reserved"
    assert by_id["cop330"].source == "pathfinder_selected"
    assert by_id["cop330"].is_favorite is True
    assert "fav320" not in by_id
    assert plan.explanation.metrics.fixed_session_count == 2
    assert plan.explanation.metrics.blocked_time_usage.excluded_candidate_count == 1


def test_unresolved_reserved_session_fails_closed(tmp_path) -> None:
    planner, _ = _fixture_planner(tmp_path)
    with pytest.raises(
        ScheduleIntegrationError, match="missing from the local catalog"
    ):
        planner.plan(
            AttendeeSchedule(reserved_session_ids=["missing"]),
            AttendeeProfile(),
        )


def test_unknown_event_timezone_fails_explicitly(tmp_path) -> None:
    planner, schedule = _fixture_planner(tmp_path)
    with pytest.raises(ScheduleIntegrationError, match="unknown event_timezone"):
        planner.plan(schedule, AttendeeProfile(), event_timezone="Nowhere/Unknown")


def test_personal_time_spanning_local_midnight_blocks_both_dates(tmp_path) -> None:
    zone = ZoneInfo("America/Los_Angeles")
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    repository.upsert_many(
        [
            Session(
                id="before",
                title="Security before break",
                start_at=datetime(2026, 11, 30, 22, tzinfo=zone),
                end_at=datetime(2026, 11, 30, 23, tzinfo=zone),
            ),
            Session(
                id="late",
                title="Security late Monday",
                start_at=datetime(2026, 11, 30, 23, 30, tzinfo=zone),
                end_at=datetime(2026, 11, 30, 23, 59, tzinfo=zone),
            ),
            Session(
                id="early",
                title="Security early Tuesday",
                start_at=datetime(2026, 12, 1, 0, 30, tzinfo=zone),
                end_at=datetime(2026, 12, 1, 1, tzinfo=zone),
            ),
        ]
    )
    schedule = AttendeeSchedule(
        personal_time=[
            PersonalTime(
                id="overnight",
                title="Personal time",
                start_at=datetime(2026, 12, 1, 7, tzinfo=UTC),
                end_at=datetime(2026, 12, 1, 9, tzinfo=UTC),
            )
        ]
    )
    plan = ExistingSchedulePlanner(repository).plan(
        schedule, AttendeeProfile(), query="security"
    )
    assert plan.proposed_addition_ids == ["before"]
    assert {
        item.hit.session.id
        for item in plan.schedule.rejected_sessions
        if item.reason == "blocked_time_conflict"
    } == {"late", "early"}
    assert plan.schedule.constraints.blocked_time_count == 2


def test_utc_catalog_sessions_use_event_clock_for_personal_time(tmp_path) -> None:
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    repository.upsert_many(
        [
            Session(
                id="before",
                title="Security before break",
                start_at=datetime(2026, 12, 1, 19, tzinfo=UTC),
                end_at=datetime(2026, 12, 1, 20, tzinfo=UTC),
            ),
            Session(
                id="during",
                title="Security during break",
                start_at=datetime(2026, 12, 1, 21, 30, tzinfo=UTC),
                end_at=datetime(2026, 12, 1, 22, 30, tzinfo=UTC),
            ),
        ]
    )
    schedule = AttendeeSchedule(
        personal_time=[
            PersonalTime(
                id="break",
                title="Personal time",
                start_at=datetime(2026, 12, 1, 21, tzinfo=UTC),
                end_at=datetime(2026, 12, 2, 1, tzinfo=UTC),
            )
        ]
    )
    plan = ExistingSchedulePlanner(repository).plan(
        schedule, AttendeeProfile(), query="security"
    )
    assert plan.proposed_addition_ids == ["before"]
    assert plan.schedule.rejected_sessions[0].reason == "blocked_time_conflict"
    assert plan.session_items[0].session.start_at.hour == 11
    assert repository.get("before").start_at.hour == 19


def test_integration_is_deterministic(tmp_path) -> None:
    planner, attendee_schedule = _fixture_planner(tmp_path)
    profile = AttendeeProfile(interests=["serverless", "security", "observability"])
    first = planner.plan(attendee_schedule, profile, query="serverless security")
    second = planner.plan(attendee_schedule, profile, query="serverless security")
    assert first == second
