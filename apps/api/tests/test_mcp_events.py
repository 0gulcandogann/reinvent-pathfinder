import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.catalog.sqlite import SqliteSessionRepository
from app.catalog.sync import sync_catalog
from app.mcp.events import (
    REQUIRED_ARGUMENTS,
    AwsEventsMcpClient,
    FakeMcpToolInvoker,
    McpToolError,
    SdkMcpToolInvoker,
)
from app.mutations.executor import MutationExecutionError, MutationExecutor
from app.mutations.models import MutationAction, ScheduleMutationPlan
from app.schedule.models import AttendeeSchedule
from app.schedule.normalize import normalize_schedule


def test_fake_mcp_pages_sync_into_same_local_catalog(tmp_path) -> None:
    fixture = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "data"
            / "fixtures"
            / "agent_catalog.json"
        ).read_text(encoding="utf-8")
    )

    def list_page(arguments):
        return (
            {"items": fixture[2:]}
            if arguments.get("nextToken") == "next"
            else {"items": fixture[:2], "nextToken": "next"}
        )

    invoker = FakeMcpToolInvoker(
        {
            "ListSessions": list_page,
            "GetSession": fixture[0],
            "GetSchedule": {
                "schedule": {
                    "reserved": ["sec340"],
                    "favorites": ["con410"],
                    "personalTime": [],
                }
            },
        }
    )
    client = AwsEventsMcpClient(invoker)
    repository = SqliteSessionRepository(tmp_path / "catalog.sqlite3")
    asyncio.run(sync_catalog(client, repository))
    assert len(repository.list_all()) == len(fixture)
    assert asyncio.run(client.get_session("mon310"))["sessionId"] == "mon310"
    schedule = normalize_schedule(asyncio.run(client.get_schedule()))
    assert schedule.reserved_session_ids == ["sec340"]
    assert schedule.favorite_session_ids == ["con410"]
    assert invoker.calls[0] == ("ListSessions", {"eventId": "reinvent2026"})
    assert invoker.calls[1] == (
        "ListSessions",
        {"eventId": "reinvent2026", "nextToken": "next"},
    )


def test_fake_mcp_partial_reservation_runs_through_m7_verification() -> None:
    reserved = []

    def get_schedule(_arguments):
        return {
            "schedule": {
                "reserved": list(reserved),
                "favorites": [],
                "personalTime": [],
            }
        }

    def reserve(_arguments):
        reserved.append("a")
        return {
            "result": {
                "successful": ["a"],
                "failed": [{"sessionId": "b", "code": "sessionFull"}],
            }
        }

    invoker = FakeMcpToolInvoker(
        {"GetSchedule": get_schedule, "ReserveSessions": reserve}
    )
    client = AwsEventsMcpClient(invoker, enable_writes=True)
    plan = ScheduleMutationPlan(
        baseline_schedule=AttendeeSchedule(),
        additions=[
            MutationAction(
                session_id=session_id,
                action="reserve",
                reason="selected_by_pathfinder",
                provenance="pathfinder_selected",
            )
            for session_id in ("a", "b")
        ],
    )
    result = asyncio.run(MutationExecutor(client).execute(plan, confirmed=True))
    assert result.status == "partially_completed"
    assert result.reservation_result.succeeded == ["a"]
    assert result.reservation_result.failed[0].code == "sessionFull"
    assert result.verified_schedule.reserved_session_ids == ["a"]


def test_mcp_write_flag_is_off_and_arbitrary_tools_are_unavailable() -> None:
    invoker = FakeMcpToolInvoker({})
    client = AwsEventsMcpClient(invoker)
    with pytest.raises(McpToolError, match="disabled"):
        asyncio.run(client.reserve_sessions(["a"]))
    assert invoker.calls == []
    with pytest.raises(MutationExecutionError, match="disabled"):
        asyncio.run(
            MutationExecutor(client).execute(
                ScheduleMutationPlan(baseline_schedule=AttendeeSchedule()),
                confirmed=True,
            )
        )


def test_mcp_tool_failure_and_malformed_payload_are_safe() -> None:
    secret = "private-token"
    broken = AwsEventsMcpClient(
        FakeMcpToolInvoker({"GetSchedule": RuntimeError(secret)})
    )
    with pytest.raises(McpToolError) as error:
        asyncio.run(broken.get_schedule())
    assert secret not in str(error.value)

    malformed = AwsEventsMcpClient(
        FakeMcpToolInvoker({"ListSessions": {"items": "bad"}})
    )

    async def read():
        return [item async for item in malformed.list_sessions()]

    with pytest.raises(McpToolError, match="items list"):
        asyncio.run(read())

    malformed_entry = AwsEventsMcpClient(
        FakeMcpToolInvoker({"ListSessions": {"items": [42]}})
    )

    async def read_entry():
        return [item async for item in malformed_entry.list_sessions()]

    with pytest.raises(McpToolError, match="malformed session"):
        asyncio.run(read_entry())

    bad_schedule = AwsEventsMcpClient(
        FakeMcpToolInvoker({"GetSchedule": {"schedule": []}})
    )
    with pytest.raises(McpToolError, match="malformed schedule"):
        asyncio.run(bad_schedule.get_schedule())

    bad_session = AwsEventsMcpClient(
        FakeMcpToolInvoker({"GetSession": {"sessionId": "other", "title": "Wrong"}})
    )
    with pytest.raises(McpToolError, match="different session ID"):
        asyncio.run(bad_session.get_session("requested"))


class _SdkSession:
    def __init__(self, *, malformed=False, read_only=False):
        self.malformed = malformed
        self.read_only = read_only
        self.calls = []

    async def list_tools(self):
        tools = [
            SimpleNamespace(
                name=name,
                inputSchema={"type": "object", "required": sorted(required)},
            )
            for name, required in REQUIRED_ARGUMENTS.items()
            if not self.read_only
            or name not in {"ReserveSessions", "CancelReservation"}
        ]
        if self.malformed:
            next(tool for tool in tools if tool.name == "GetSchedule").inputSchema[
                "required"
            ] = ["wrong"]
        return SimpleNamespace(tools=tools)

    async def call_tool(self, name, *, arguments):
        self.calls.append((name, arguments))
        return SimpleNamespace(
            isError=False,
            structuredContent={
                "schedule": {"reserved": [], "favorites": [], "personalTime": []}
            },
        )


def test_sdk_invoker_checks_advertised_tool_schemas_before_calls() -> None:
    session = _SdkSession()
    client = AwsEventsMcpClient(SdkMcpToolInvoker(session))
    assert (
        normalize_schedule(asyncio.run(client.get_schedule())).reserved_session_ids
        == []
    )
    assert session.calls == [("GetSchedule", {"eventId": "reinvent2026"})]

    mismatched = _SdkSession(malformed=True)
    client = AwsEventsMcpClient(SdkMcpToolInvoker(mismatched))
    with pytest.raises(McpToolError, match="GetSchedule failed"):
        asyncio.run(client.get_schedule())
    assert mismatched.calls == []

    read_only = _SdkSession(read_only=True)
    client = AwsEventsMcpClient(SdkMcpToolInvoker(read_only))
    assert (
        normalize_schedule(asyncio.run(client.get_schedule())).reserved_session_ids
        == []
    )
