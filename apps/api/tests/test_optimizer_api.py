import asyncio

from fastapi.testclient import TestClient

from app.catalog.sqlite import SqliteSessionRepository
from app.catalog.sync import sync_catalog
from app.clients.fake import FakeEventsClient
from app.main import app


def _catalog(tmp_path, monkeypatch) -> None:
    database = tmp_path / "catalog.sqlite3"
    sessions = [
        {
            "sessionId": "plain",
            "title": "Serverless basics",
            "sessionTime": {
                "date": "2026-12-01",
                "time": "10:00",
                "length": "60",
                "timezone": "America/Los_Angeles",
            },
        },
        {
            "sessionId": "lambda",
            "title": "Serverless with Lambda",
            "services": ["AWS Lambda"],
            "sessionTime": {
                "date": "2026-12-01",
                "time": "10:00",
                "length": "60",
                "timezone": "America/Los_Angeles",
            },
        },
    ]
    asyncio.run(
        sync_catalog(FakeEventsClient(sessions), SqliteSessionRepository(database))
    )
    monkeypatch.setenv("PATHFINDER_CATALOG_DB", str(database))
    monkeypatch.delenv("AWS_EVENTS_ACCESS_TOKEN", raising=False)


def test_optimize_endpoint_uses_m3_scores_and_local_catalog(
    tmp_path, monkeypatch
) -> None:
    _catalog(tmp_path, monkeypatch)
    response = TestClient(app).post(
        "/schedule/optimize",
        json={
            "query": "serverless",
            "profile": {"preferred_services": ["AWS Lambda"]},
            "candidate_limit": 20,
        },
    )
    assert response.status_code == 200
    schedule = response.json()
    assert [item["hit"]["session"]["id"] for item in schedule["selected_sessions"]] == [
        "lambda"
    ]
    assert schedule["selected_sessions"][0]["hit"]["preference_score"] == 5
    assert schedule["rejected_sessions"][0]["reason"] == "time_conflict"
    assert schedule["candidate_count"] == 2


def test_optimize_endpoint_validates_profile_and_fixed_constraints(
    tmp_path, monkeypatch
) -> None:
    _catalog(tmp_path, monkeypatch)
    client = TestClient(app)
    malformed = client.post(
        "/schedule/optimize",
        json={
            "profile": {
                "blocked_times": [{"day": "Noday", "start": "13:00", "end": "17:00"}]
            }
        },
    )
    assert malformed.status_code == 422

    fixed = {
        "id": "fixed",
        "title": "Already attending",
        "start_at": "2026-12-01T10:00:00-08:00",
        "end_at": "2026-12-01T11:00:00-08:00",
    }
    response = client.post(
        "/schedule/optimize",
        json={
            "query": "serverless",
            "profile": {
                "blocked_times": [{"day": "Tuesday", "start": "09:00", "end": "12:00"}]
            },
            "fixed_sessions": [fixed],
        },
    )
    assert response.status_code == 422
    assert "fixed session fixed overlaps a blocked time" == response.json()["detail"]

    too_many_candidates = client.post(
        "/schedule/optimize",
        json={"profile": {}, "candidate_limit": 501},
    )
    assert too_many_candidates.status_code == 422


def test_explain_endpoint_adds_explanations_and_candidate_cap(
    tmp_path, monkeypatch
) -> None:
    _catalog(tmp_path, monkeypatch)
    response = TestClient(app).post(
        "/schedule/explain",
        json={
            "query": "serverless",
            "profile": {"preferred_services": ["AWS Lambda"]},
            "candidate_limit": 1,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["schedule"]["candidate_count"] == 1
    selected = body["explanation"]["sessions"][0]
    assert selected["session_id"] == "lambda"
    assert selected["matched_preferred_services"] == ["AWS Lambda"]
    assert body["explanation"]["rejected"][0]["reason"] == "candidate_cap"
    assert body["explanation"]["metrics"]["candidate_cap_excluded_count"] == 1
