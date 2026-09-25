import asyncio
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.catalog.sqlite import SqliteSessionRepository
from app.clients.fake import FakeEventsClient
from app.models.profile import AttendeeProfile
from app.models.session import Session
from app.mutations.executor import (
    MutationExecutionError,
    MutationExecutor,
)
from app.mutations.models import MutationAction, Replacement, ScheduleMutationPlan
from app.mutations.planner import MutationPlanError, MutationPlanner
from app.optimizer.solve import optimize_schedule
from app.ranking.session_search import SearchHit
from app.schedule.models import AttendeeSchedule, PersonalTime

ZONE = ZoneInfo("America/Los_Angeles")


def _session(session_id: str, hour: int, *, day: int = 30) -> Session:
    return Session(
        id=session_id,
        title=f"Session {session_id}",
        start_at=datetime(
            2026, 11 if day == 30 else 12, day if day == 30 else 1, hour, tzinfo=ZONE
        ),
        end_at=datetime(
            2026,
            11 if day == 30 else 12,
            day if day == 30 else 1,
            hour + 1,
            tzinfo=ZONE,
        ),
    )


def _fixture(tmp_path: Path, *, new_hour: int = 16):
    sessions = [
        _session("keep", 9),
        _session("add", 11),
        _session("old", 14),
        _session("new", new_hour),
    ]
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    repository.upsert_many(sessions)
    current = AttendeeSchedule(
        reserved_session_ids=["keep", "old"], favorite_session_ids=["add"]
    )
    target = optimize_schedule(
        [
            SearchHit(session=sessions[1], score=20),
            SearchHit(session=sessions[3], score=30),
        ],
        AttendeeProfile(),
        fixed_sessions=[sessions[0]],
    )
    plan = MutationPlanner(repository).build(
        current,
        target,
        replacements=[Replacement(old_session_id="old", new_session_id="new")],
    )
    return repository, current, target, plan


def _fake(current: AttendeeSchedule, **kwargs) -> FakeEventsClient:
    return FakeEventsClient(
        schedule={
            "schedule": {
                "reserved": list(current.reserved_session_ids),
                "favorites": list(current.favorite_session_ids),
                "personalTime": [],
            }
        },
        **kwargs,
    )


def test_plan_is_minimal_explicit_and_deterministic(tmp_path) -> None:
    repository, current, target, plan = _fixture(tmp_path)
    assert [item.session_id for item in plan.unchanged] == ["keep"]
    assert [item.session_id for item in plan.removals] == ["old"]
    assert [item.session_id for item in plan.additions] == ["add", "new"]
    assert plan.removals[0].reason == "explicit_replacement"
    assert plan.additions[0].title == "Session add"
    assert (
        MutationPlanner(repository).build(
            current,
            target,
            replacements=[Replacement(old_session_id="old", new_session_id="new")],
        )
        == plan
    )
    assert current.reserved_session_ids == ["keep", "old"]


def test_favorites_and_personal_time_do_not_create_mutations(tmp_path) -> None:
    repository, current, target, _ = _fixture(tmp_path)
    current.favorite_session_ids = ["favorite-only", "add"]
    current.personal_time = [
        PersonalTime(
            id="meeting",
            title="Meeting",
            start_at=datetime(2026, 12, 1, 21, tzinfo=UTC),
            end_at=datetime(2026, 12, 1, 22, tzinfo=UTC),
        )
    ]
    plan = MutationPlanner(repository).build(
        current, target, remove_session_ids=["old"]
    )
    assert "favorite-only" not in [item.session_id for item in plan.removals]
    assert all(
        item.action != "reserve" or item.session_id != "favorite-only"
        for item in plan.additions
    )
    assert plan.baseline_schedule.favorite_session_ids == ["favorite-only", "add"]
    assert plan.baseline_schedule.personal_time[0].id == "meeting"


def test_implicit_removal_and_unreserved_cancellation_are_rejected(tmp_path) -> None:
    repository, current, target, _ = _fixture(tmp_path)
    planner = MutationPlanner(repository)
    with pytest.raises(MutationPlanError, match="explicitly removed"):
        planner.build(current, target)
    with pytest.raises(MutationPlanError, match="existing reservations"):
        planner.build(current, target, remove_session_ids=["unrelated"])


def test_plan_rejects_personal_time_overlap_and_unpaired_replacement(tmp_path) -> None:
    repository, current, _, _ = _fixture(tmp_path, new_hour=14)
    old = repository.get("old")
    new = repository.get("new")
    target = optimize_schedule(
        [SearchHit(session=new, score=30)],
        AttendeeProfile(),
        fixed_sessions=[repository.get("keep")],
    )
    with pytest.raises(MutationPlanError, match="explicit replacement"):
        MutationPlanner(repository).build(current, target, remove_session_ids=["old"])

    current.personal_time = [
        PersonalTime(
            id="meeting",
            title="Meeting",
            start_at=new.start_at.astimezone(UTC),
            end_at=new.end_at.astimezone(UTC),
        )
    ]
    with pytest.raises(MutationPlanError, match="personal time"):
        MutationPlanner(repository).build(
            current,
            target,
            replacements=[Replacement(old_session_id=old.id, new_session_id=new.id)],
        )


def test_unconfirmed_execution_does_not_read_or_write(tmp_path) -> None:
    _, current, _, plan = _fixture(tmp_path)
    fake = _fake(current)
    result = asyncio.run(MutationExecutor(fake).execute(plan, confirmed=False))
    assert result.status == "confirmation_required"
    assert fake.write_calls == []
    assert fake.get_schedule_calls == 0


def test_confirmed_partial_success_and_safe_replacement_order(tmp_path) -> None:
    _, current, _, plan = _fixture(tmp_path)
    fake = _fake(current, reservation_failures={"add": "sessionFull"})
    result = asyncio.run(MutationExecutor(fake).execute(plan, confirmed=True))
    assert result.status == "partially_completed"
    assert result.reservation_result.succeeded == ["new"]
    assert [
        (item.session_id, item.code) for item in result.reservation_result.failed
    ] == [("add", "sessionFull")]
    assert result.cancellation_result.succeeded == ["old"]
    assert fake.write_calls == [("reserve", ["add", "new"]), ("cancel", "old")]
    assert result.verified_schedule.reserved_session_ids == ["keep", "new"]
    assert any(
        item.kind == "api_operation_failed" for item in result.verification_failures
    )


def test_full_success_and_cancellation_failure(tmp_path) -> None:
    _, current, _, plan = _fixture(tmp_path)
    success = asyncio.run(
        MutationExecutor(_fake(current)).execute(plan, confirmed=True)
    )
    assert success.status == "completed"
    assert success.reservation_result.succeeded == ["add", "new"]

    failed = asyncio.run(
        MutationExecutor(_fake(current, cancellation_failures={"old": 409})).execute(
            plan, confirmed=True
        )
    )
    assert failed.status == "partially_completed"
    assert failed.cancellation_result.failed[0].session_id == "old"
    assert failed.cancellation_result.failed[0].code == "http_409"
    assert "old" in failed.verified_schedule.reserved_session_ids


def test_multiple_reservation_batches_and_partial_failure(tmp_path) -> None:
    baseline = AttendeeSchedule()
    plan = ScheduleMutationPlan(
        baseline_schedule=baseline,
        additions=[
            MutationAction(
                session_id=f"s{number:02}",
                action="reserve",
                reason="selected_by_pathfinder",
                provenance="pathfinder_selected",
            )
            for number in range(12)
        ],
    )
    fake = _fake(
        baseline,
        reservation_failures={"s01": "sessionFull", "s11": "scheduleConflict"},
    )
    result = asyncio.run(MutationExecutor(fake).execute(plan, confirmed=True))
    assert [len(value) for kind, value in fake.write_calls if kind == "reserve"] == [
        10,
        2,
    ]
    assert len(result.reservation_result.succeeded) == 10
    assert [item.session_id for item in result.reservation_result.failed] == [
        "s01",
        "s11",
    ]
    assert result.reservation_result.failed[1].code == "scheduleConflict"


def test_stale_plan_prevents_all_writes(tmp_path) -> None:
    _, current, _, plan = _fixture(tmp_path)
    fake = _fake(AttendeeSchedule(reserved_session_ids=["keep"]))
    result = asyncio.run(MutationExecutor(fake).execute(plan, confirmed=True))
    assert result.status == "stale_plan"
    assert fake.write_calls == []


def test_reported_reservation_success_missing_from_schedule(tmp_path) -> None:
    _, current, _, plan = _fixture(tmp_path)
    stale = _fake(current).schedule
    fake = _fake(current, stale_final_schedule=stale)
    result = asyncio.run(MutationExecutor(fake).execute(plan, confirmed=True))
    assert result.status == "verification_failed"
    assert any(
        item.kind == "reported_success_missing" for item in result.verification_failures
    )
    assert ("cancel", "old") not in fake.write_calls


def test_reported_cancellation_success_still_present(tmp_path) -> None:
    _, current, _, plan = _fixture(tmp_path)
    stale = {
        "schedule": {
            "reserved": ["keep", "old", "add", "new"],
            "favorites": ["add"],
            "personalTime": [],
        }
    }
    fake = _fake(current, stale_final_schedule=stale)
    result = asyncio.run(MutationExecutor(fake).execute(plan, confirmed=True))
    assert result.status == "verification_failed"
    assert any(
        item.kind == "cancellation_still_present"
        for item in result.verification_failures
    )


def test_get_schedule_failure_is_reported_and_prevents_cancellation(tmp_path) -> None:
    _, current, _, plan = _fixture(tmp_path)
    fake = _fake(current, fail_get_schedule_on_calls={2})
    result = asyncio.run(MutationExecutor(fake).execute(plan, confirmed=True))
    assert result.status == "verification_failed"
    assert result.verification_failures[0].kind == "get_schedule_failed"
    assert ("cancel", "old") not in fake.write_calls


def test_final_get_schedule_failure_is_not_reported_as_success(tmp_path) -> None:
    _, current, _, plan = _fixture(tmp_path)
    fake = _fake(current, fail_get_schedule_on_calls={3})
    result = asyncio.run(MutationExecutor(fake).execute(plan, confirmed=True))
    assert result.status == "verification_failed"
    assert result.verification_failures[0].kind == "get_schedule_failed"
    assert ("cancel", "old") in fake.write_calls


def test_overlapping_replacement_is_deferred_without_losing_old(tmp_path) -> None:
    _, current, _, plan = _fixture(tmp_path, new_hour=14)
    assert plan.additions[-1].conflicts_with == ["old"]
    fake = _fake(current)
    result = asyncio.run(MutationExecutor(fake).execute(plan, confirmed=True))
    assert result.status == "partially_completed"
    assert ("cancel", "old") not in fake.write_calls
    assert "old" in result.verified_schedule.reserved_session_ids
    assert any(
        item.kind == "replacement_deferred" for item in result.verification_failures
    )


def test_live_client_or_missing_client_cannot_write_without_flag(tmp_path) -> None:
    _, _, _, plan = _fixture(tmp_path)
    with pytest.raises(MutationExecutionError, match="disabled"):
        asyncio.run(MutationExecutor(None).execute(plan, confirmed=True))


def test_forged_plan_cannot_cancel_unrelated_session(tmp_path) -> None:
    _, current, _, plan = _fixture(tmp_path)
    bad = plan.model_copy(deep=True)
    bad.removals[0].session_id = "unrelated"
    fake = _fake(current)
    with pytest.raises(MutationExecutionError):
        asyncio.run(MutationExecutor(fake).execute(bad, confirmed=True))
    assert fake.write_calls == []
