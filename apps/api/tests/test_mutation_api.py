from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.api.mutations import get_write_client
from app.catalog.sqlite import SqliteSessionRepository
from app.clients.fake import FakeEventsClient
from app.main import app
from app.models.profile import AttendeeProfile
from app.models.session import Session
from app.optimizer.solve import optimize_schedule
from app.ranking.session_search import SearchHit
from app.schedule.models import AttendeeSchedule


def _request(tmp_path, monkeypatch):
    zone = ZoneInfo("America/Los_Angeles")

    def session(session_id, hour):
        return Session(
            id=session_id,
            title=f"Session {session_id}",
            start_at=datetime(2026, 11, 30, hour, tzinfo=zone),
            end_at=datetime(2026, 11, 30, hour + 1, tzinfo=zone),
        )

    existing = session("existing", 9)
    added = session("added", 11)
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    repository.upsert_many([existing, added])
    monkeypatch.setenv("PATHFINDER_CATALOG_DB", str(tmp_path / "catalog.sqlite3"))
    monkeypatch.delenv("AWS_EVENTS_ENABLE_WRITES", raising=False)
    monkeypatch.delenv("AWS_EVENTS_ACCESS_TOKEN", raising=False)
    optimized = optimize_schedule(
        [SearchHit(session=added, score=25)],
        AttendeeProfile(),
        fixed_sessions=[existing],
    )
    current = AttendeeSchedule(reserved_session_ids=["existing"])
    return {
        "current_schedule": current.model_dump(mode="json"),
        "optimized_schedule": optimized.model_dump(mode="json"),
    }


def test_plan_endpoint_is_side_effect_free_and_execute_requires_confirmation(
    tmp_path, monkeypatch
) -> None:
    request = _request(tmp_path, monkeypatch)
    client = TestClient(app)
    plan_response = client.post("/schedule/mutations/plan", json=request)
    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert [item["session_id"] for item in plan["additions"]] == ["added"]
    assert [item["session_id"] for item in plan["unchanged"]] == ["existing"]
    assert plan["removals"] == []

    unconfirmed = client.post(
        "/schedule/mutations/execute", json={"plan": plan, "confirmed": False}
    )
    assert unconfirmed.status_code == 200
    assert unconfirmed.json()["status"] == "confirmation_required"
    disabled = client.post(
        "/schedule/mutations/execute", json={"plan": plan, "confirmed": True}
    )
    assert disabled.status_code == 403
    assert "disabled" in disabled.json()["detail"]


def test_execute_endpoint_uses_injected_fake_and_validates_input(
    tmp_path, monkeypatch
) -> None:
    request = _request(tmp_path, monkeypatch)
    client = TestClient(app)
    plan = client.post("/schedule/mutations/plan", json=request).json()
    fake = FakeEventsClient(
        schedule={
            "schedule": {
                "reserved": ["existing"],
                "favorites": [],
                "personalTime": [],
            }
        }
    )
    app.dependency_overrides[get_write_client] = lambda: fake
    try:
        response = client.post(
            "/schedule/mutations/execute", json={"plan": plan, "confirmed": True}
        )
    finally:
        app.dependency_overrides.pop(get_write_client, None)
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["verified_schedule"]["reserved_session_ids"] == [
        "existing",
        "added",
    ]
    assert fake.write_calls == [("reserve", ["added"])]

    invalid = client.post(
        "/schedule/mutations/plan",
        json={**request, "remove_session_ids": ["not-reserved"]},
    )
    assert invalid.status_code == 422
