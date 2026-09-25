"""Compare offline profile rankings against the same local fixture catalog."""

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
from app.models.profile import AttendeeProfile  # noqa: E402

FIXTURE_PATH = ROOT / "data" / "fixtures" / "reinvent_sessions.json"
PERSONAS_PATH = ROOT / "data" / "fixtures" / "personas.json"
QUERY = "serverless"


async def main() -> None:
    sessions = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    personas = json.loads(PERSONAS_PATH.read_text(encoding="utf-8"))
    with TemporaryDirectory() as directory:
        repository = SqliteSessionRepository(Path(directory) / "catalog.sqlite3")
        await sync_catalog(FakeEventsClient(sessions), repository)
        search = SessionSearchService(repository)
        print(f"Query: {QUERY}")
        for name, raw_profile in personas.items():
            profile = AttendeeProfile.model_validate(raw_profile)
            print(f"\n{name}:")
            for hit in search.search(QUERY, profile=profile, limit=3).results:
                explanation = (
                    f"bonuses {hit.preference_contributions}, penalties {hit.penalties}"
                )
                print(
                    f"  {hit.session.code}: {hit.session.title} "
                    f"(total {hit.score} = text {hit.text_score} "
                    f"+ preferences {hit.preference_score}; {explanation})"
                )


if __name__ == "__main__":
    asyncio.run(main())
