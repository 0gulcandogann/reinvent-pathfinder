"""Show local search results from fake re:Invent sessions without AWS access."""

import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.catalog.search_service import SessionSearchService  # noqa: E402
from app.catalog.sqlite import SqliteSessionRepository  # noqa: E402
from app.catalog.sync import sync_catalog  # noqa: E402
from app.clients.fake import FakeEventsClient  # noqa: E402
from app.ranking.session_search import SearchFilters  # noqa: E402

FIXTURE_PATH = ROOT / "data" / "fixtures" / "reinvent_sessions.json"


async def main() -> None:
    raw_sessions = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    with TemporaryDirectory() as directory:
        repository = SqliteSessionRepository(Path(directory) / "catalog.sqlite3")
        await sync_catalog(FakeEventsClient(raw_sessions), repository)
        search = SessionSearchService(repository)
        examples = [
            ("advanced serverless observability", SearchFilters()),
            ("cold starts", SearchFilters()),
            ("serverless", SearchFilters(levels=("300",), services=("AWS Lambda",))),
        ]
        for query, filters in examples:
            results = search.search(query, filters, limit=3)
            print(f"Query: {query} | Matches: {results.total}")
            for hit in results.results:
                print(
                    f"  {hit.session.code}: {hit.session.title} "
                    f"(score {hit.score}, fields {hit.field_scores})"
                )


if __name__ == "__main__":
    asyncio.run(main())
