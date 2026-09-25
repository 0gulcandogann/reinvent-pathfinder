import asyncio

from fastapi.testclient import TestClient

from app.catalog.sqlite import SqliteSessionRepository
from app.catalog.sync import sync_catalog
from app.clients.fake import FakeEventsClient
from app.main import app


def test_search_endpoint_reads_local_sqlite_only(
    tmp_path, raw_sessions, monkeypatch
) -> None:
    database = tmp_path / "catalog.sqlite3"
    repository = SqliteSessionRepository(database)
    asyncio.run(sync_catalog(FakeEventsClient(raw_sessions), repository))
    monkeypatch.setenv("PATHFINDER_CATALOG_DB", str(database))
    monkeypatch.delenv("AWS_EVENTS_ACCESS_TOKEN", raising=False)

    response = TestClient(app).get(
        "/sessions/search",
        params={
            "query": "advanced serverless observability",
            "level": "400",
            "session_type": "Workshop",
            "service": "AWS Lambda",
            "topic": "Observability",
            "track": "Compute",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["results"][0]["session"]["code"] == "SVS401"
    assert body["results"][0]["field_scores"]


def test_search_endpoint_empty_database(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PATHFINDER_CATALOG_DB", str(tmp_path / "empty.sqlite3"))
    response = TestClient(app).get("/sessions/search", params={"query": "lambda"})
    assert response.status_code == 200
    assert response.json() == {"total": 0, "results": []}


def test_recommend_endpoint_uses_local_catalog_and_explains_score(
    tmp_path, raw_sessions, monkeypatch
) -> None:
    database = tmp_path / "catalog.sqlite3"
    repository = SqliteSessionRepository(database)
    asyncio.run(sync_catalog(FakeEventsClient(raw_sessions), repository))
    monkeypatch.setenv("PATHFINDER_CATALOG_DB", str(database))
    monkeypatch.delenv("AWS_EVENTS_ACCESS_TOKEN", raising=False)

    response = TestClient(app).post(
        "/sessions/recommend",
        json={
            "query": "serverless",
            "profile": {
                "interests": ["security", "IAM", "containers"],
                "desired_levels": ["300", "400"],
                "prioritize_depth": True,
            },
            "filters": {"levels": ["300", "400"]},
        },
    )
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["session"]["code"] == "SEC330"
    assert result["score"] == result["text_score"] + result["preference_score"]
    assert result["preference_contributions"]["interests"] > 0
    assert result["matched_preferences"]["interests"] == ["security", "IAM"]


def test_recommend_endpoint_rejects_malformed_profile(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PATHFINDER_CATALOG_DB", str(tmp_path / "empty.sqlite3"))
    client = TestClient(app)
    for profile in (
        {"desired_levels": "300"},
        {"blocked_times": [{"day": "Tuesday", "start": "17:00", "end": "12:00"}]},
        {"unexpected": True},
    ):
        response = client.post(
            "/sessions/recommend", json={"query": "serverless", "profile": profile}
        )
        assert response.status_code == 422
