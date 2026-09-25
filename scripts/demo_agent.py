"""Offline multi-turn Pathfinder agent with typed intents and fake MCP."""

import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.agent.models import AgentContext  # noqa: E402
from app.agent.parser import FakeIntentParser  # noqa: E402
from app.agent.service import PathfinderAgent  # noqa: E402
from app.catalog.sqlite import SqliteSessionRepository  # noqa: E402
from app.catalog.sync import sync_catalog  # noqa: E402
from app.clients.fake import FakeEventsClient  # noqa: E402
from app.mcp.events import AwsEventsMcpClient, FakeMcpToolInvoker  # noqa: E402
from app.schedule.normalize import normalize_schedule  # noqa: E402


async def main() -> None:
    catalog = json.loads(
        (ROOT / "data" / "fixtures" / "agent_catalog.json").read_text(encoding="utf-8")
    )
    raw_schedule = {
        "schedule": {"reserved": ["sec340"], "favorites": [], "personalTime": []}
    }
    fake = FakeEventsClient(catalog, schedule=raw_schedule)
    mcp = AwsEventsMcpClient(FakeMcpToolInvoker({"GetSchedule": raw_schedule}))
    print("FAKE AWS EVENTS MCP")
    mcp_schedule = normalize_schedule(await mcp.get_schedule())
    print(f"  GetSchedule reserved: {mcp_schedule.reserved_session_ids}")
    with TemporaryDirectory() as directory:
        repository = SqliteSessionRepository(Path(directory) / "catalog.sqlite3")
        await sync_catalog(fake, repository)
        context = AgentContext(
            current_schedule=normalize_schedule(await fake.get_schedule())
        )
        agent = PathfinderAgent(repository, FakeIntentParser(), fake)
        messages = [
            "I'm a platform engineer interested in serverless, security and "
            "observability. Prefer Level 300 and 400. Keep Tuesday afternoon "
            "free. Avoid unnecessary venue changes.",
            "Make Wednesday less busy.",
            "Replace my Wednesday 2 PM session with something more advanced "
            "about containers.",
            "Do it.",
        ]
        for message in messages:
            response = await agent.handle(message, context)
            print(f"\nUSER: {message}")
            print(f"INTENT: {response.intent}")
            print(f"SERVICE: {response.invoked_service or 'none'}")
            print(f"PATHFINDER: {response.message}")
            if response.pending_plan_id:
                plan = context.pending_plan
                print(f"PENDING PLAN: {response.pending_plan_id}")
                print(f"  reserve: {[item.session_id for item in plan.additions]}")
                print(f"  cancel: {[item.session_id for item in plan.removals]}")
            if response.intent == "reoptimize_schedule" and context.latest_schedule:
                print(f"  daily counts: {context.latest_schedule.sessions_per_day}")
            if response.intent == "confirm_schedule_mutation":
                result = response.data
                print(f"  reservation: {result['reservation_result']['succeeded']}")
                print(f"  cancellation: {result['cancellation_result']['succeeded']}")
                print(
                    f"  verified: {result['verified_schedule']['reserved_session_ids']}"
                )


if __name__ == "__main__":
    asyncio.run(main())
