import asyncio

from app.catalog.normalize import normalize_session
from app.catalog.search_service import SessionSearchService
from app.catalog.sqlite import SqliteSessionRepository
from app.catalog.sync import sync_catalog
from app.clients.fake import FakeEventsClient
from app.ranking.session_search import SearchFilters, rank_sessions


def _service(tmp_path, raw_sessions) -> SessionSearchService:
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    asyncio.run(sync_catalog(FakeEventsClient(raw_sessions), repository))
    return SessionSearchService(repository)


def test_search_by_title_abstract_and_service(tmp_path, raw_sessions) -> None:
    service = _service(tmp_path, raw_sessions)
    assert service.search("performance tuning").results[0].session.code == "SVS301"
    assert service.search("cold starts").results[0].session.code == "SVS301"
    cloudwatch = service.search("CloudWatch")
    assert {hit.session.code for hit in cloudwatch.results} == {"SVS401", "COP310"}


def test_combined_filters_and_text_query(tmp_path, raw_sessions) -> None:
    service = _service(tmp_path, raw_sessions)
    filters = SearchFilters(
        levels=("300", "400"),
        session_types=("Workshop",),
        services=("AWS Lambda",),
        topics=("Observability",),
        tracks=("Compute",),
    )
    result = service.search("advanced serverless observability", filters)
    assert result.total == 1
    assert result.results[0].session.code == "SVS401"
    assert result.results[0].score > 0
    assert result.results[0].matched_terms == [
        "advanced",
        "serverless",
        "observability",
    ]


def test_filters_or_within_field_and_and_across_fields(tmp_path, raw_sessions) -> None:
    service = _service(tmp_path, raw_sessions)
    filters = SearchFilters(levels=("300,400",), services=("AWS Lambda",))
    result = service.search(filters=filters)
    assert {hit.session.code for hit in result.results} == {
        "SVS401",
        "SVS301",
        "SEC330",
    }
    assert all(hit.score == 0 for hit in result.results)


def test_title_match_ranks_above_abstract_only_match() -> None:
    title_match = normalize_session({"sessionId": "title", "title": "Lambda internals"})
    abstract_match = normalize_session(
        {"sessionId": "abstract", "title": "Runtime internals", "abstract": "Lambda"}
    )
    hits = rank_sessions([abstract_match, title_match], "lambda", SearchFilters())
    assert [hit.session.id for hit in hits] == ["title", "abstract"]
    assert hits[0].field_scores == {"title": 12}
    assert hits[1].field_scores == {"abstract": 2}


def test_deterministic_ranking_and_empty_query(tmp_path, raw_sessions) -> None:
    service = _service(tmp_path, raw_sessions)
    first = service.search("serverless")
    second = service.search("serverless")
    assert [hit.session.id for hit in first.results] == [
        hit.session.id for hit in second.results
    ]
    all_sessions = service.search(limit=3)
    assert all_sessions.total == len(raw_sessions)
    assert len(all_sessions.results) == 3
    assert all(hit.score == 0 for hit in all_sessions.results)
    assert (
        all_sessions.results[0].session.title
        == "Advanced serverless observability with AWS Lambda"
    )


def test_no_results(tmp_path, raw_sessions) -> None:
    service = _service(tmp_path, raw_sessions)
    result = service.search("quantum entanglement")
    assert result.total == 0
    assert result.results == []


def test_malformed_optional_fields_remain_safe_after_sync(tmp_path) -> None:
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    client = FakeEventsClient(
        [
            {
                "sessionId": "valid",
                "title": "Sparse",
                "services": None,
                "speakers": [42],
            },
            {"sessionId": "bad"},
        ]
    )
    result = asyncio.run(sync_catalog(client, repository))
    assert (result.fetched, result.normalized, result.skipped) == (2, 1, 1)
    persisted = repository.get("valid")
    assert persisted is not None
    assert persisted.services == []
    assert persisted.speakers == []
    assert SessionSearchService(repository).search("sparse").total == 1
