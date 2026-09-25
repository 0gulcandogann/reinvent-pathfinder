import asyncio
import json

import pytest

from app.catalog.search_service import SessionSearchService
from app.catalog.sqlite import SqliteSessionRepository
from app.catalog.sync import CatalogSyncError, sync_catalog
from app.clients.fake import FakeEventsClient


def test_sync_skips_bad_entries_and_writes_normalized_catalog(tmp_path) -> None:
    client = FakeEventsClient(
        [
            {"sessionId": "1", "title": "Good"},
            {"sessionId": "2"},
            None,
            {"sessionId": "3", "title": "Also good", "services": ["Lambda"]},
        ]
    )
    output = tmp_path / "catalog.json"
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    result = asyncio.run(sync_catalog(client, repository, output))

    assert (result.fetched, result.normalized, result.skipped, result.errors) == (
        4,
        2,
        2,
        0,
    )
    catalog = json.loads(output.read_text(encoding="utf-8"))
    assert [session["id"] for session in catalog] == ["1", "3"]
    assert catalog[1]["services"] == ["Lambda"]
    assert repository.count() == 2


def test_repeated_full_sync_upserts_without_duplicates(tmp_path, raw_sessions) -> None:
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    first = asyncio.run(sync_catalog(FakeEventsClient(raw_sessions), repository))
    second = asyncio.run(sync_catalog(FakeEventsClient(raw_sessions), repository))
    assert first.normalized == second.normalized == len(raw_sessions)
    assert repository.count() == len(raw_sessions)


def test_successful_full_sync_prunes_missing_sessions_and_is_idempotent(
    tmp_path,
) -> None:
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    first_generation = [
        {"sessionId": "A", "title": "Alpha session"},
        {"sessionId": "B", "title": "Bravo session"},
        {"sessionId": "C", "title": "Charlie session"},
    ]
    second_generation = [first_generation[0], first_generation[2]]

    asyncio.run(sync_catalog(FakeEventsClient(first_generation), repository))
    assert repository.count() == 3

    asyncio.run(sync_catalog(FakeEventsClient(second_generation), repository))
    assert [session.id for session in repository.list_all()] == ["A", "C"]
    assert repository.get("B") is None
    assert SessionSearchService(repository).search("bravo").total == 0

    after_second = repository.list_all()
    asyncio.run(sync_catalog(FakeEventsClient(second_generation), repository))
    assert repository.list_all() == after_second
    assert repository.count() == 2


def test_failed_full_walk_preserves_last_known_good_catalog(tmp_path) -> None:
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    snapshot = tmp_path / "catalog.json"
    first_generation = [
        {"sessionId": "A", "title": "Alpha session"},
        {"sessionId": "B", "title": "Bravo session"},
        {"sessionId": "C", "title": "Charlie session"},
    ]
    asyncio.run(sync_catalog(FakeEventsClient(first_generation), repository, snapshot))
    before_sessions = repository.list_all()
    before_snapshot = snapshot.read_bytes()

    class FailingEventsClient:
        async def list_sessions(self):
            yield {"sessionId": "A", "title": "Changed but incomplete"}
            raise RuntimeError("upstream walk interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        asyncio.run(sync_catalog(FailingEventsClient(), repository, snapshot))

    assert repository.list_all() == before_sessions
    assert [session.id for session in repository.list_all()] == ["A", "B", "C"]
    assert snapshot.read_bytes() == before_snapshot


def test_observed_but_malformed_session_keeps_last_known_good_row(tmp_path) -> None:
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    initial = [
        {"sessionId": "A", "title": "Alpha session"},
        {"sessionId": "B", "title": "Bravo session"},
    ]
    asyncio.run(sync_catalog(FakeEventsClient(initial), repository))

    result = asyncio.run(
        sync_catalog(
            FakeEventsClient(
                [{"sessionId": "A", "title": "Alpha updated"}, {"sessionId": "B"}]
            ),
            repository,
        )
    )
    assert result.skipped == 1
    assert repository.get("A").title == "Alpha updated"
    assert repository.get("B").title == "Bravo session"
    assert repository.count() == 2


def test_all_malformed_generation_preserves_previous_catalog(tmp_path) -> None:
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    snapshot = tmp_path / "catalog.json"
    asyncio.run(
        sync_catalog(
            FakeEventsClient([{"sessionId": "A", "title": "Alpha"}]),
            repository,
            snapshot,
        )
    )
    before = snapshot.read_bytes()
    with pytest.raises(CatalogSyncError, match="no valid sessions"):
        asyncio.run(
            sync_catalog(
                FakeEventsClient([None, {"sessionId": "A"}]), repository, snapshot
            )
        )
    assert repository.get("A").title == "Alpha"
    assert snapshot.read_bytes() == before
