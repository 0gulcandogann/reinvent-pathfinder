"""Opt-in, process-local demo data; never connects to AWS."""

import asyncio
import json
import os
from pathlib import Path

from pydantic import BaseModel

from app.catalog.sqlite import SqliteSessionRepository, catalog_db_path
from app.catalog.sync import sync_catalog
from app.clients.fake import FakeEventsClient
from app.models.profile import AttendeeProfile, TimeBlock
from app.schedule.models import AttendeeSchedule
from app.schedule.normalize import normalize_schedule

FIXTURES = Path(__file__).resolve().parents[4] / "data" / "fixtures"


def demo_enabled() -> bool:
    return os.getenv("PATHFINDER_DEMO_MODE", "false").casefold() == "true"


class DemoBootstrap(BaseModel):
    mode: str = "offline_fixture"
    profile: AttendeeProfile
    existing_schedule: AttendeeSchedule
    catalog_sessions: int


class DemoState:
    def __init__(self) -> None:
        self.fake: FakeEventsClient | None = None
        self.profile: AttendeeProfile | None = None
        self.lock = asyncio.Lock()

    async def ensure(self) -> DemoBootstrap:
        async with self.lock:
            if self.fake is None:
                return await self._reset()
            return await self._snapshot()

    async def reset(self) -> DemoBootstrap:
        async with self.lock:
            return await self._reset()

    async def _reset(self) -> DemoBootstrap:
        catalog = [
            *json.loads((FIXTURES / "existing_schedule_catalog.json").read_text()),
            *json.loads((FIXTURES / "agent_catalog.json").read_text()),
        ]
        by_id = {item["sessionId"]: item for item in catalog}
        raw_schedule = json.loads((FIXTURES / "aws_get_schedule.json").read_text())
        raw_schedule["schedule"]["reserved"].append("sec340")
        self.fake = FakeEventsClient(by_id.values(), schedule=raw_schedule)
        self.profile = AttendeeProfile(
            interests=["serverless", "security", "observability"],
            preferred_services=["AWS Lambda"],
            desired_levels=["300", "400"],
            learning_goals=["observability", "security"],
            blocked_times=[TimeBlock(day="Tuesday", start="13:00", end="17:00")],
            max_sessions_per_day=5,
            minimize_venue_changes=True,
            prioritize_depth=True,
        )
        repository = SqliteSessionRepository(catalog_db_path())
        await sync_catalog(self.fake, repository)
        return await self._snapshot()

    async def _snapshot(self) -> DemoBootstrap:
        assert self.fake is not None and self.profile is not None
        return DemoBootstrap(
            profile=self.profile.model_copy(deep=True),
            existing_schedule=normalize_schedule(await self.fake.get_schedule()),
            catalog_sessions=SqliteSessionRepository(catalog_db_path()).count(),
        )


demo_state = DemoState()
