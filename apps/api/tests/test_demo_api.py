import asyncio

from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.api.agent import sessions
from app.auth.connection import BuilderIdConnection
from app.demo.state import demo_state
from app.main import app


def test_demo_endpoints_are_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("PATHFINDER_DEMO_MODE", raising=False)
    client = TestClient(app)
    assert client.get("/demo/state").status_code == 404
    assert client.post("/demo/reset").status_code == 404


def test_demo_profile_to_verified_replacement_and_reset(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PATHFINDER_DEMO_MODE", "true")
    monkeypatch.setenv("PATHFINDER_CATALOG_DB", str(tmp_path / "demo.sqlite3"))
    demo_state.fake = None
    sessions.contexts.clear()
    sessions.locks.clear()
    client = TestClient(app)
    bootstrap = client.get("/demo/state").json()
    assert bootstrap["mode"] == "offline_fixture"
    assert bootstrap["catalog_sessions"] > 8
    assert bootstrap["existing_schedule"]["reserved_session_ids"] == [
        "sec310",
        "svs320",
        "sec340",
    ]
    conversation = "demo-test"

    def message(text: str, **kwargs):
        response = client.post(
            "/agent/message",
            json={"conversation_id": conversation, "message": text, **kwargs},
        )
        assert response.status_code == 200
        return response.json()

    without_plan = message("Do it.")
    assert without_plan["status"] == "needs_context"
    assert demo_state.fake.write_calls == []

    optimized = message(
        "Build my week around serverless security observability.",
        profile=bootstrap["profile"],
        current_schedule=bootstrap["existing_schedule"],
    )
    assert optimized["status"] == "ok"
    assert optimized["data"]["schedule"]["selected_sessions"]
    assert optimized["data"]["schedule"]["constraints"]["blocked_time_count"] == 1
    lighter = message("Make Wednesday less busy.")
    assert lighter["status"] == "ok"
    replacement = message(
        "Replace my Wednesday 2 PM session with something more advanced "
        "about containers."
    )
    assert replacement["status"] == "confirmation_required"
    assert replacement["data"]["plan"]["replacements"] == [
        {
            "old_session_id": "sec340",
            "new_session_id": "con410",
            "reason": "explicit_replacement",
        }
    ]
    assert demo_state.fake.write_calls == []
    wrong = message("Confirm plan wrong-id")
    assert wrong["status"] == "needs_context"
    assert demo_state.fake.write_calls == []

    discarded = message("Discard plan.")
    assert discarded["status"] == "ok"
    assert message("Do it.")["status"] == "needs_context"
    assert demo_state.fake.write_calls == []
    message(
        "Build my week around serverless security observability.",
        profile=bootstrap["profile"],
        current_schedule=bootstrap["existing_schedule"],
    )
    message("Make Wednesday less busy.")
    replacement = message(
        "Replace my Wednesday 2 PM session with something more advanced "
        "about containers."
    )

    confirmed = message(f"Confirm plan {replacement['pending_plan_id']}")
    assert confirmed["data"]["status"] in {"completed", "partially_completed"}
    verified = confirmed["data"]["verified_schedule"]
    assert "con410" in verified["reserved_session_ids"]
    assert "sec340" not in verified["reserved_session_ids"]
    assert demo_state.fake.write_calls

    reset = client.post("/demo/reset").json()
    assert reset["existing_schedule"]["reserved_session_ids"] == [
        "sec310",
        "svs320",
        "sec340",
    ]
    assert demo_state.fake.write_calls == []
    assert sessions.contexts == {}


def test_demo_mode_never_uses_live_write_client(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PATHFINDER_DEMO_MODE", "true")
    monkeypatch.setenv("AWS_EVENTS_ENABLE_WRITES", "true")
    monkeypatch.setenv("AWS_EVENTS_ACCESS_TOKEN", "private-test-token")
    monkeypatch.setenv("PATHFINDER_CATALOG_DB", str(tmp_path / "demo.sqlite3"))
    client = TestClient(app)
    response = client.post(
        "/schedule/mutations/execute",
        json={
            "confirmed": True,
            "plan": {
                "baseline_schedule": {
                    "reserved_session_ids": [],
                    "favorite_session_ids": [],
                    "personal_time": [],
                }
            },
        },
    )
    assert response.status_code == 403
    assert "disabled" in response.json()["detail"]
    assert "private-test-token" not in response.text


def test_demo_reset_never_imports_live_attendee_state(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PATHFINDER_DEMO_MODE", "true")
    monkeypatch.setenv("AWS_EVENTS_ENABLE_WRITES", "false")
    monkeypatch.setenv("PATHFINDER_CATALOG_DB", str(tmp_path / "demo.sqlite3"))

    async def login(_open_browser) -> str:
        return "private-live-token"

    async def check(_token: str) -> None:
        return None

    connection = BuilderIdConnection(login=login, check_access=check)

    async def connect() -> None:
        await connection.start()
        await connection._task

    asyncio.run(connect())
    assert connection.status().state == "live_aws"
    monkeypatch.setattr(auth_api, "connection", connection)

    client = TestClient(app)
    reset = client.post("/demo/reset")
    assert reset.status_code == 200
    assert reset.json()["mode"] == "offline_fixture"
    assert reset.json()["existing_schedule"]["reserved_session_ids"] == [
        "sec310",
        "svs320",
        "sec340",
    ]
    assert client.get("/auth/builder-id/status").json() == {"state": "live_aws"}
    assert "private-live-token" not in reset.text
    assert demo_state.fake.write_calls == []
    assert sessions.contexts == {}
