"""Merge a fake AWS attendee schedule into local Pathfinder optimization."""

import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.catalog.sqlite import SqliteSessionRepository  # noqa: E402
from app.catalog.sync import sync_catalog  # noqa: E402
from app.clients.fake import FakeEventsClient  # noqa: E402
from app.models.profile import AttendeeProfile  # noqa: E402
from app.schedule.integration import ExistingSchedulePlanner  # noqa: E402
from app.schedule.normalize import normalize_schedule  # noqa: E402

CATALOG_PATH = ROOT / "data" / "fixtures" / "existing_schedule_catalog.json"
SCHEDULE_PATH = ROOT / "data" / "fixtures" / "aws_get_schedule.json"


async def main() -> None:
    raw_sessions = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    raw_schedule = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
    fake = FakeEventsClient(raw_sessions, schedule=raw_schedule)
    profile = AttendeeProfile(
        interests=["serverless", "security", "observability"],
        preferred_services=["AWS Lambda"],
        desired_levels=["300", "400"],
        max_sessions_per_day=5,
        minimize_venue_changes=True,
        prioritize_depth=True,
    )
    with TemporaryDirectory() as directory:
        repository = SqliteSessionRepository(Path(directory) / "catalog.sqlite3")
        await sync_catalog(fake, repository)
        attendee_schedule = normalize_schedule(await fake.get_schedule())
        result = ExistingSchedulePlanner(repository).plan(
            attendee_schedule,
            profile,
            query="serverless security observability",
        )

    print("EXISTING AWS SCHEDULE (offline fixture)")
    for session_id in attendee_schedule.reserved_session_ids:
        item = next(
            item for item in result.session_items if item.session.id == session_id
        )
        session = item.session
        print(
            f"  {session.start_at:%A %H:%M} {session.code} "
            f"[existing_reserved] {session.title}"
        )
    for item in result.personal_time_items:
        print(
            f"  {item.event_local_start_at:%A %H:%M}-"
            f"{item.event_local_end_at:%H:%M} PERSONAL TIME "
            f"[personal_time] {item.block.title}"
        )
    print(f"  Favorites: {', '.join(result.favorite_session_ids)}")

    print("\nPATHFINDER OPTIMIZED ITINERARY")
    itinerary = [
        (
            item.session.start_at,
            f"  {item.session.start_at:%A %H:%M} {item.session.code} "
            f"[{item.source}]"
            f"{' [favorite]' if item.is_favorite else ''} {item.session.title}",
        )
        for item in result.session_items
    ]
    itinerary.extend(
        (
            item.event_local_start_at,
            f"  {item.event_local_start_at:%A %H:%M}-"
            f"{item.event_local_end_at:%H:%M} PERSONAL TIME [personal_time]",
        )
        for item in result.personal_time_items
    )
    for _, description in sorted(itinerary, key=lambda item: item[0]):
        print(description)

    print("\nREJECTED CONFLICTS")
    for item in result.schedule.rejected_sessions:
        if item.reason in {"fixed_session_conflict", "blocked_time_conflict"}:
            print(f"  {item.hit.session.code}: {item.reason}")

    blocked_conflicts = sum(
        item.reason == "blocked_time_conflict"
        for item in result.schedule.rejected_sessions
    )
    print("\nMETRICS")
    print(f"  Fixed sessions: {len(result.already_reserved_ids)}")
    print(f"  Pathfinder-added sessions: {len(result.proposed_addition_ids)}")
    print(f"  Blocked-time conflicts: {blocked_conflicts}")
    print(f"  Venue transitions: {result.schedule.venue_transitions}")
    print(f"  Total utility: {result.schedule.score:g}")


if __name__ == "__main__":
    asyncio.run(main())
