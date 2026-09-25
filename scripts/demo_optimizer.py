"""Build a two-day itinerary entirely from fixture sessions."""

import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.catalog.search_service import SessionSearchService  # noqa: E402
from app.catalog.sqlite import SqliteSessionRepository  # noqa: E402
from app.catalog.sync import sync_catalog  # noqa: E402
from app.clients.fake import FakeEventsClient  # noqa: E402
from app.models.profile import WEEKDAY_NAMES, AttendeeProfile  # noqa: E402
from app.optimizer.solve import optimize_schedule  # noqa: E402

FIXTURE_PATH = ROOT / "data" / "fixtures" / "optimizer_sessions.json"
QUERY = "serverless security observability"


async def main() -> None:
    raw_sessions = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    profile = AttendeeProfile(
        interests=["serverless", "security", "observability"],
        preferred_services=["AWS Lambda"],
        desired_levels=["300", "400"],
        blocked_times=[{"day": "Tuesday", "start": "13:00", "end": "17:00"}],
        max_sessions_per_day=5,
        minimize_venue_changes=True,
        prioritize_depth=True,
    )
    with TemporaryDirectory() as directory:
        repository = SqliteSessionRepository(Path(directory) / "catalog.sqlite3")
        await sync_catalog(FakeEventsClient(raw_sessions), repository)
        search = SessionSearchService(repository)
        candidates = search.search(QUERY, profile=profile, limit=150).results
        fixed = repository.get("plt-m1")
        assert fixed is not None
        schedule = optimize_schedule(candidates, profile, fixed_sessions=[fixed])

    print("Platform Engineer | offline fixture itinerary")
    print(f"Query: {QUERY}")
    days = sorted(schedule.sessions_per_day)
    for day in days:
        day_date = date.fromisoformat(day)
        weekday = WEEKDAY_NAMES[day_date.weekday()]
        print(f"\n{weekday.upper()} {day}")
        events = []
        for item in schedule.selected_sessions:
            session = item.hit.session
            if session.start_at and session.start_at.date() == day_date:
                events.append((session.start_at.time(), "session", item))
        for block in profile.blocked_times:
            if block.day.casefold() == weekday.casefold():
                events.append((block.start, "block", block))
        for _, kind, value in sorted(events, key=lambda event: event[0]):
            if kind == "block":
                print(f"  {value.start:%H:%M}-{value.end:%H:%M} BLOCKED")
            else:
                session = value.hit.session
                fixed_label = " [FIXED]" if value.fixed else ""
                location = session.venue or "venue unknown"
                print(
                    f"  {session.start_at:%H:%M}-{session.end_at:%H:%M} "
                    f"{session.code} {session.title} ({location}){fixed_label}"
                )

    print(f"\nTotal optimizer score: {schedule.score:g}")
    print(f"Selected sessions: {len(schedule.selected_sessions)}")
    print(f"Rejected time conflicts: {schedule.rejected_conflict_count}")
    print(f"Venue transitions: {schedule.venue_transitions}")
    print(f"Sessions per day: {schedule.sessions_per_day}")


if __name__ == "__main__":
    asyncio.run(main())
