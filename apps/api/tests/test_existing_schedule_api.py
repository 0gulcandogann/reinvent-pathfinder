import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.catalog.sqlite import SqliteSessionRepository
from app.catalog.sync import sync_catalog
from app.clients.fake import FakeEventsClient
from app.main import app
from app.schedule.normalize import normalize_schedule

ROOT = Path(__file__).resolve().parents[3]


def _request(tmp_path, monkeypatch) -> dict:
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
    database = tmp_path / "catalog.sqlite3"
    asyncio.run(
        sync_catalog(FakeEventsClient(catalog), SqliteSessionRepository(database))
    )
    monkeypatch.setenv("PATHFINDER_CATALOG_DB", str(database))
    monkeypatch.delenv("AWS_EVENTS_ACCESS_TOKEN", raising=False)
    return {
        "query": "serverless security observability",
        "profile": {"interests": ["serverless", "security", "observability"]},
        "existing_schedule": normalize_schedule(raw_schedule).model_dump(mode="json"),
    }


def test_existing_schedule_endpoint_is_offline_and_preserves_provenance(
    tmp_path, monkeypatch
) -> None:
    request = _request(tmp_path, monkeypatch)
    response = TestClient(app).post("/schedule/optimize-existing", json=request)
    assert response.status_code == 200
    result = response.json()
    assert result["already_reserved_ids"] == ["sec310", "svs320"]
    assert "cop330" in result["proposed_addition_ids"]
    assert result["personal_time_items"][0]["source"] == "personal_time"
    assert result["personal_time_items"][0]["event_local_start_at"].startswith(
        "2026-12-01T13:00:00"
    )
    assert result["explanation"]["metrics"]["fixed_session_count"] == 2
    assert {item["session"]["id"]: item["source"] for item in result["session_items"]}[
        "sec310"
    ] == "existing_reserved"


def test_existing_schedule_endpoint_validates_payload_and_missing_commitments(
    tmp_path, monkeypatch
) -> None:
    request = _request(tmp_path, monkeypatch)
    client = TestClient(app)
    request["existing_schedule"]["personal_time"][0]["end_at"] = "2026-12-01T20:00:00Z"
    assert client.post("/schedule/optimize-existing", json=request).status_code == 422

    request = _request(tmp_path, monkeypatch)
    request["existing_schedule"]["reserved_session_ids"] = ["missing"]
    response = client.post("/schedule/optimize-existing", json=request)
    assert response.status_code == 422
    assert "missing from the local catalog" in response.json()["detail"]


def test_existing_schedule_endpoint_rejects_bad_profile_and_timezone(
    tmp_path, monkeypatch
) -> None:
    request = _request(tmp_path, monkeypatch)
    client = TestClient(app)
    request["profile"]["max_sessions_per_day"] = 0
    assert client.post("/schedule/optimize-existing", json=request).status_code == 422

    request = _request(tmp_path, monkeypatch)
    request["event_timezone"] = "Invalid/Zone"
    response = client.post("/schedule/optimize-existing", json=request)
    assert response.status_code == 422
    assert response.json()["detail"] == "unknown event_timezone"
