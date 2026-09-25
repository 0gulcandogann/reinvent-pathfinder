"""The optional Live view must never reuse fixture data or enable writes."""

import asyncio

from fastapi.testclient import TestClient

from app.api import live as live_api
from app.auth.connection import BuilderIdConnection
from app.clients.fake import FakeEventsClient
from app.main import app


def _connected() -> BuilderIdConnection:
    async def login(_open_browser) -> str:
        return "private-test-token"

    async def check(_token: str) -> None:
        return None

    connection = BuilderIdConnection(login=login, check_access=check)

    async def connect() -> None:
        await connection.start()
        await connection._task

    asyncio.run(connect())
    return connection


def test_live_bridge_requires_confirmed_attendee_access(monkeypatch) -> None:
    monkeypatch.setattr(live_api, "_require_local", lambda _request: None)
    monkeypatch.setattr(live_api, "connection", BuilderIdConnection())
    monkeypatch.setattr(live_api, "_catalog_ready", False)
    client = TestClient(app)
    assert client.post("/live/bootstrap").status_code == 403
    assert (
        client.post(
            "/live/agent/message",
            json={"message": "Do it.", "conversation_id": "live-test"},
        ).status_code
        == 403
    )


def test_live_bridge_uses_separate_read_only_catalog(monkeypatch, tmp_path) -> None:
    fake = FakeEventsClient(
        [
            {
                "sessionId": "live-a",
                "title": "Real attendee session",
                "sessionTime": {
                    "date": "2026-11-30",
                    "time": "09:00",
                    "length": "60",
                    "timezone": "America/Los_Angeles",
                },
            }
        ],
        schedule={
            "schedule": {"reserved": ["live-a"], "favorites": [], "personalTime": []}
        },
    )

    class LiveFake:
        def __init__(self, token: str, *, enable_writes: bool) -> None:
            assert token == "private-test-token"
            assert enable_writes is False

        async def __aenter__(self):
            return fake

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(live_api, "_require_local", lambda _request: None)
    monkeypatch.setattr(live_api, "connection", _connected())
    monkeypatch.setattr(live_api, "_catalog_path", tmp_path / "live.sqlite3")
    monkeypatch.setattr(live_api, "_catalog_ready", False)
    monkeypatch.setattr(live_api, "AwsEventsRestClient", LiveFake)
    client = TestClient(app)
    bootstrap = client.post("/live/bootstrap")
    assert bootstrap.status_code == 200
    assert bootstrap.json()["existing_schedule"]["reserved_session_ids"] == ["live-a"]
    assert bootstrap.json()["catalog_sessions"] == 1
    results = client.post(
        "/live/sessions/recommend",
        json={"query": "attendee", "profile": {}, "filters": {}},
    )
    assert results.status_code == 200
    assert [item["session"]["id"] for item in results.json()["results"]] == ["live-a"]
    optimized = client.post(
        "/live/agent/message",
        json={
            "message": "Build my week around attendee.",
            "conversation_id": "live-planning",
            "profile": {"interests": ["attendee"]},
            "current_schedule": bootstrap.json()["existing_schedule"],
        },
    )
    assert optimized.status_code == 200
    assert optimized.json()["status"] == "ok"
    assert optimized.json()["data"]["already_reserved_ids"] == ["live-a"]
    assert all(
        item["session"]["id"] == "live-a"
        for item in optimized.json()["data"]["session_items"]
    )
    response = client.post(
        "/live/agent/message",
        json={"message": "Do it.", "conversation_id": "live-test"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert fake.write_calls == []
    assert "private-test-token" not in bootstrap.text + results.text + response.text
