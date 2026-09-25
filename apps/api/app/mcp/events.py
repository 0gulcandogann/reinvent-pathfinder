"""Allowlisted AWS Events MCP tools behind the existing EventsClient shape."""

import json
from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any, Protocol

from app.catalog.normalize import MalformedSessionError, normalize_session
from app.mutations.models import ReservationResult
from app.mutations.normalize import RESERVATION_BATCH_SIZE, normalize_reservation_result
from app.schedule.normalize import normalize_schedule

AWS_EVENTS_MCP_URL = "https://api.awsevents.com/mcp"
ALLOWED_TOOLS = frozenset(
    {
        "ListSessions",
        "GetSession",
        "GetSchedule",
        "ReserveSessions",
        "CancelReservation",
    }
)
REQUIRED_ARGUMENTS = {
    "ListSessions": {"eventId"},
    "GetSession": {"eventId", "sessionId"},
    "GetSchedule": {"eventId"},
    "ReserveSessions": {"eventId", "sessionIds"},
    "CancelReservation": {"eventId", "sessionId"},
}


class McpToolError(RuntimeError):
    """MCP transport, tool, or response failure with redacted details."""


class McpToolInvoker(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, object]) -> object: ...


class SdkMcpToolInvoker:
    """Wrap an initialized MCP SDK session without owning OAuth credentials."""

    def __init__(self, session: object) -> None:
        self.session = session
        self._schemas: dict[str, set[str]] | None = None

    async def verify_contract(self, name: str) -> None:
        """Check live-advertised input schemas before permitting any tool call."""
        if self._schemas is None:
            try:
                listing = await self.session.list_tools()
            except Exception as error:
                raise McpToolError("AWS Events MCP tool discovery failed") from error
            tools = getattr(listing, "tools", None)
            if not isinstance(tools, list):
                raise McpToolError("AWS Events MCP tool discovery was malformed")
            found: dict[str, set[str]] = {}
            for tool in tools:
                tool_name = getattr(tool, "name", None)
                schema = getattr(tool, "inputSchema", None)
                if schema is None:
                    schema = getattr(tool, "input_schema", None)
                if tool_name in ALLOWED_TOOLS and isinstance(schema, dict):
                    found[tool_name] = set(schema.get("required", []))
            self._schemas = found
        if self._schemas.get(name) != REQUIRED_ARGUMENTS[name]:
            raise McpToolError(
                "AWS Events MCP tool schemas differ from expected contract"
            )

    async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        if name not in ALLOWED_TOOLS:
            raise McpToolError("Unsupported AWS Events MCP tool")
        await self.verify_contract(name)
        try:
            result = await self.session.call_tool(name, arguments=arguments)
        except Exception as error:
            raise McpToolError(f"AWS Events MCP {name} failed") from error
        if getattr(result, "isError", False) or getattr(result, "is_error", False):
            raise McpToolError(f"AWS Events MCP {name} returned a tool error")
        structured = getattr(result, "structuredContent", None)
        if structured is None:
            structured = getattr(result, "structured_content", None)
        if structured is not None:
            return structured
        content = getattr(result, "content", None)
        if name == "CancelReservation" and content == []:
            return {}
        if not isinstance(content, list) or len(content) != 1:
            raise McpToolError("AWS Events MCP returned malformed content")
        block = content[0]
        text = getattr(block, "text", None)
        if not isinstance(text, str):
            raise McpToolError("AWS Events MCP returned non-JSON content")
        try:
            return json.loads(text)
        except ValueError as error:
            raise McpToolError("AWS Events MCP returned invalid JSON") from error


class FakeMcpToolInvoker:
    """Scripted MCP tool responses and errors for credential-free tests."""

    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = deepcopy(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        self.calls.append((name, deepcopy(arguments)))
        response = self.responses.get(name)
        if isinstance(response, Exception):
            raise response
        if callable(response):
            response = response(arguments)
        return deepcopy(response)


class AwsEventsMcpClient:
    """EventsClient-compatible facade over fixed official MCP tool names."""

    def __init__(
        self,
        invoker: McpToolInvoker,
        event_id: str = "reinvent2026",
        *,
        enable_writes: bool = False,
    ) -> None:
        if not event_id.strip():
            raise ValueError("event ID is required")
        self.invoker = invoker
        self.event_id = event_id
        self.enable_writes = enable_writes

    async def list_sessions(self) -> AsyncIterator[object]:
        token: str | None = None
        seen: set[str] = set()
        while True:
            arguments: dict[str, object] = {"eventId": self.event_id}
            if token is not None:
                arguments["nextToken"] = token
            page = await self._call("ListSessions", arguments)
            items = page.get("items")
            if not isinstance(items, list):
                raise McpToolError("ListSessions returned no items list")
            for item in items:
                if not isinstance(item, dict):
                    raise McpToolError("ListSessions returned a malformed session")
                yield item
            next_token = page.get("nextToken")
            if next_token is None:
                return
            if not isinstance(next_token, str) or not next_token or next_token in seen:
                raise McpToolError("ListSessions returned an invalid nextToken")
            seen.add(next_token)
            token = next_token

    async def get_session(self, session_id: str) -> object:
        if not session_id.strip():
            raise ValueError("session ID is required")
        payload = await self._call(
            "GetSession", {"eventId": self.event_id, "sessionId": session_id}
        )
        try:
            normalized = normalize_session(payload)
        except MalformedSessionError as error:
            raise McpToolError("GetSession returned a malformed session") from error
        if normalized.id != session_id:
            raise McpToolError("GetSession returned a different session ID")
        return payload

    async def get_schedule(self) -> object:
        payload = await self._call("GetSchedule", {"eventId": self.event_id})
        try:
            normalize_schedule(payload)
        except ValueError as error:
            raise McpToolError("GetSchedule returned a malformed schedule") from error
        return payload

    async def reserve_sessions(self, session_ids: list[str]) -> ReservationResult:
        self._require_writes()
        if not 1 <= len(session_ids) <= RESERVATION_BATCH_SIZE:
            raise ValueError("reservation batch must contain 1 to 10 IDs")
        if len(set(session_ids)) != len(session_ids):
            raise ValueError("reservation IDs must be distinct")
        payload = await self._call(
            "ReserveSessions",
            {"eventId": self.event_id, "sessionIds": session_ids},
        )
        return normalize_reservation_result(payload, session_ids)

    async def cancel_reservation(self, session_id: str) -> None:
        self._require_writes()
        if not session_id.strip():
            raise ValueError("session ID is required")
        await self._call(
            "CancelReservation",
            {"eventId": self.event_id, "sessionId": session_id},
        )

    def _require_writes(self) -> None:
        if not self.enable_writes:
            raise McpToolError("AWS Events MCP schedule writes are disabled")

    async def _call(self, name: str, arguments: dict[str, object]) -> dict[str, Any]:
        if name not in ALLOWED_TOOLS:
            raise McpToolError("Unsupported AWS Events MCP tool")
        try:
            payload = await self.invoker.call_tool(name, arguments)
        except Exception as error:
            raise McpToolError(f"AWS Events MCP {name} failed") from error
        if not isinstance(payload, dict):
            raise McpToolError(f"AWS Events MCP {name} returned a non-object result")
        return payload
