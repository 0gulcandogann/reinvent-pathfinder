import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent.parser import FakeIntentParser
from app.agent.service import PathfinderAgent
from app.api.agent import get_pathfinder_agent
from app.catalog.sqlite import SqliteSessionRepository
from app.catalog.sync import sync_catalog
from app.clients.fake import FakeEventsClient
from app.main import app


def _fixture(tmp_path, monkeypatch):
    catalog = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "data"
            / "fixtures"
            / "agent_catalog.json"
        ).read_text(encoding="utf-8")
    )
    raw_schedule = {
        "schedule": {"reserved": ["sec340"], "favorites": [], "personalTime": []}
    }
    fake = FakeEventsClient(catalog, schedule=raw_schedule)
    database = tmp_path / "catalog.sqlite3"
    asyncio.run(sync_catalog(fake, SqliteSessionRepository(database)))
    monkeypatch.setenv("PATHFINDER_CATALOG_DB", str(database))
    monkeypatch.delenv("AWS_EVENTS_ENABLE_WRITES", raising=False)
    return fake


def test_agent_endpoint_is_thin_offline_and_validates_request(tmp_path, monkeypatch):
    fake = _fixture(tmp_path, monkeypatch)
    client = TestClient(app)
    conversation_id = f"agent-api-{tmp_path.name}"
    no_plan = client.post(
        "/agent/message",
        json={"conversation_id": conversation_id, "message": "Do it."},
    )
    assert no_plan.status_code == 200
    assert no_plan.json()["status"] == "needs_context"
    assert fake.write_calls == []

    profile = client.post(
        "/agent/message",
        json={
            "conversation_id": conversation_id,
            "message": "I'm interested in serverless, security and observability.",
            "current_schedule": {
                "reserved_session_ids": ["sec340"],
                "favorite_session_ids": [],
                "personal_time": [],
            },
        },
    )
    assert profile.status_code == 200
    assert profile.json()["intent"] == "set_profile"
    assert profile.json()["invoked_service"] == "ExistingSchedulePlanner"
    lighter = client.post(
        "/agent/message",
        json={
            "conversation_id": conversation_id,
            "message": "Make Wednesday less busy.",
        },
    )
    assert lighter.status_code == 200
    assert lighter.json()["intent"] == "reoptimize_schedule"
    assert (
        client.post(
            "/agent/message",
            json={
                "conversation_id": conversation_id,
                "message": "Do it.",
                "profile": {"max_sessions_per_day": 0},
            },
        ).status_code
        == 422
    )


def test_agent_endpoint_fake_confirmation_flow(tmp_path, monkeypatch):
    fake = _fixture(tmp_path, monkeypatch)
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    agent = PathfinderAgent(repository, FakeIntentParser(), fake)
    app.dependency_overrides[get_pathfinder_agent] = lambda: agent
    client = TestClient(app)
    conversation_id = f"agent-confirm-{tmp_path.name}"
    try:
        client.post(
            "/agent/message",
            json={
                "conversation_id": conversation_id,
                "message": "I'm interested in security and containers.",
                "current_schedule": {
                    "reserved_session_ids": ["sec340"],
                    "favorite_session_ids": [],
                    "personal_time": [],
                },
            },
        )
        planned = client.post(
            "/agent/message",
            json={
                "conversation_id": conversation_id,
                "message": "Replace Wednesday 2 PM with advanced containers.",
            },
        )
        assert planned.json()["requires_confirmation"] is True
        assert fake.write_calls == []
        executed = client.post(
            "/agent/message",
            json={"conversation_id": conversation_id, "message": "Do it."},
        )
    finally:
        app.dependency_overrides.pop(get_pathfinder_agent, None)
    assert executed.status_code == 200
    assert executed.json()["data"]["status"] == "completed"
    assert fake.write_calls == [("reserve", ["con410"]), ("cancel", "sec340")]
