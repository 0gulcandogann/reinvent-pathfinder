import sqlite3

import pytest

from app.catalog.normalize import normalize_session
from app.catalog.sqlite import SqliteSessionRepository


def test_insert_upsert_and_round_trip_lists(tmp_path, raw_sessions) -> None:
    database = tmp_path / "nested" / "catalog.sqlite3"
    repository = SqliteSessionRepository(database)
    original = normalize_session(raw_sessions[0])
    assert repository.upsert_many([original]) == 1
    assert repository.count() == 1
    restored = repository.get(original.id)
    assert restored == original
    assert restored.tracks == ["Compute"]
    assert restored.topics == ["Serverless", "Observability"]
    assert restored.industries == ["Financial Services"]
    assert restored.roles == ["Platform Engineer"]
    assert restored.services == ["AWS Lambda", "Amazon CloudWatch"]
    assert restored.speakers == ["Avery Chen"]

    updated = original.model_copy(
        update={"title": "Updated title", "services": ["AWS Lambda"]}
    )
    assert repository.upsert_many([updated]) == 1
    assert repository.count() == 1
    assert repository.get(original.id) == updated
    assert repository.list_all() == [updated]

    reopened = SqliteSessionRepository(database)
    assert reopened.get(original.id) == updated


def test_repository_handles_missing_optional_fields(tmp_path) -> None:
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    session = normalize_session({"sessionId": "minimal", "title": "Minimal"})
    repository.upsert_many([session])
    restored = repository.get("minimal")
    assert restored is not None
    assert restored.abstract is None
    assert restored.services == []
    assert restored.speakers == []
    assert restored.start_at is None
    assert repository.get("missing") is None


def test_failed_generation_write_rolls_back_upserts_and_pruning(tmp_path) -> None:
    database = tmp_path / "catalog.sqlite3"
    repository = SqliteSessionRepository(database)
    original_a = normalize_session({"sessionId": "A", "title": "Original A"})
    original_b = normalize_session({"sessionId": "B", "title": "Original B"})
    repository.replace_all([original_a, original_b])

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_new_session BEFORE INSERT ON sessions
            WHEN NEW.session_id = 'C'
            BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END
            """
        )

    changed_a = original_a.model_copy(update={"title": "Changed A"})
    new_c = normalize_session({"sessionId": "C", "title": "New C"})
    with pytest.raises(sqlite3.IntegrityError, match="simulated write failure"):
        repository.replace_all([changed_a, new_c])

    assert repository.list_all() == [original_a, original_b]
