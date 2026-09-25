"""Show a confirmed, fake-only reservation workflow with partial success."""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.catalog.sqlite import SqliteSessionRepository  # noqa: E402
from app.clients.fake import FakeEventsClient  # noqa: E402
from app.models.profile import AttendeeProfile  # noqa: E402
from app.models.session import Session  # noqa: E402
from app.mutations.executor import MutationExecutor  # noqa: E402
from app.mutations.models import Replacement  # noqa: E402
from app.mutations.planner import MutationPlanner  # noqa: E402
from app.optimizer.solve import optimize_schedule  # noqa: E402
from app.ranking.session_search import SearchHit  # noqa: E402
from app.schedule.normalize import normalize_schedule  # noqa: E402

ZONE = ZoneInfo("America/Los_Angeles")


def _session(session_id: str, title: str, hour: int) -> Session:
    return Session(
        id=session_id,
        code=session_id.upper(),
        title=title,
        start_at=datetime(2026, 11, 30, hour, tzinfo=ZONE),
        end_at=datetime(2026, 11, 30, hour + 1, tzinfo=ZONE),
        venue="The Venetian",
    )


async def main() -> None:
    sessions = [
        _session("sec310", "Security foundations", 9),
        _session("cop330", "Cloud operations", 11),
        _session("svs320", "Current serverless session", 14),
        _session("svs401", "Advanced serverless workshop", 16),
    ]
    with TemporaryDirectory() as directory:
        repository = SqliteSessionRepository(Path(directory) / "catalog.sqlite3")
        repository.upsert_many(sessions)
        fake = FakeEventsClient(
            schedule={
                "schedule": {
                    "reserved": ["sec310", "svs320"],
                    "favorites": ["cop330"],
                    "personalTime": [],
                }
            },
            reservation_failures={"cop330": "sessionFull"},
        )
        current = normalize_schedule(await fake.get_schedule())
        target = optimize_schedule(
            [
                SearchHit(session=repository.get("cop330"), score=30),
                SearchHit(session=repository.get("svs401"), score=40),
            ],
            AttendeeProfile(),
            fixed_sessions=[repository.get("sec310")],
        )
        plan = MutationPlanner(repository).build(
            current,
            target,
            replacements=[
                Replacement(old_session_id="svs320", new_session_id="svs401")
            ],
        )

        print("CURRENT SCHEDULE")
        for session_id in current.reserved_session_ids:
            session = repository.get(session_id)
            print(f"  {session.start_at:%H:%M} {session.code} [existing_reserved]")
        print("\nPROPOSED CHANGES (no writes)")
        for label, actions in (
            ("KEEP", plan.unchanged),
            ("CANCEL", plan.removals),
            ("RESERVE", plan.additions),
        ):
            print(f"  {label}: {', '.join(item.session_id for item in actions)}")
        executor = MutationExecutor(fake)
        unconfirmed = await executor.execute(plan, confirmed=False)
        print(f"  Unconfirmed: {unconfirmed.status}; writes: {len(fake.write_calls)}")

        result = await executor.execute(plan, confirmed=True)
        print("\nCONFIRMED EXECUTION")
        for session_id in result.reservation_result.succeeded:
            print(f"  Reserved: {session_id}")
        for failure in result.reservation_result.failed:
            print(f"  Reservation failed: {failure.session_id} ({failure.code})")
        for session_id in result.cancellation_result.succeeded:
            print(f"  Cancelled: {session_id}")
        print("\nGETSCHEDULE VERIFICATION")
        print(f"  Status: {result.status}")
        print(
            "  Final reserved: "
            + ", ".join(result.verified_schedule.reserved_session_ids)
        )


if __name__ == "__main__":
    asyncio.run(main())
