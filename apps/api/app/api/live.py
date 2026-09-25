"""Local, read-only bridge from a confirmed Builder ID session to Pathfinder."""

import asyncio
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.agent.context import InMemoryAgentSessions
from app.agent.models import AgentResponse
from app.agent.parser import FakeIntentParser
from app.agent.service import PathfinderAgent
from app.api.agent import AgentMessageRequest
from app.api.auth import connection
from app.api.search import RecommendationRequest
from app.catalog.search_service import SessionSearchService
from app.catalog.sqlite import DEFAULT_DB_PATH, SqliteSessionRepository
from app.catalog.sync import CatalogSyncError, sync_catalog
from app.clients.events_api import AwsEventsRestClient, EventsApiError
from app.ranking.session_search import SearchResults
from app.schedule.models import AttendeeSchedule
from app.schedule.normalize import ScheduleNormalizationError, normalize_schedule

router = APIRouter(prefix="/live")
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_catalog_path: Path = DEFAULT_DB_PATH.with_name("live_catalog.sqlite3")
_catalog_ready = False
_load_lock = asyncio.Lock()
_sessions = InMemoryAgentSessions()


class LiveBootstrap(BaseModel):
    mode: Literal["live_aws"] = "live_aws"
    existing_schedule: AttendeeSchedule
    catalog_sessions: int


def _require_local(request: Request) -> None:
    if (
        request.url.hostname not in _LOOPBACK
        or request.client is None
        or request.client.host not in _LOOPBACK
    ):
        raise HTTPException(status_code=403, detail="Live local access is unavailable")


def _require_live(request: Request) -> str:
    _require_local(request)
    token = connection.live_access_token()
    if token is None:
        raise HTTPException(status_code=403, detail="Attendee access is not confirmed")
    return token


@router.post("/bootstrap", response_model=LiveBootstrap)
async def live_bootstrap(request: Request) -> LiveBootstrap:
    token = _require_live(request)
    async with _load_lock:
        try:
            async with AwsEventsRestClient(token, enable_writes=False) as client:
                schedule = normalize_schedule(await client.get_schedule())
                repository = SqliteSessionRepository(_catalog_path)
                await sync_catalog(client, repository)
        except (EventsApiError, ScheduleNormalizationError, CatalogSyncError) as error:
            raise HTTPException(
                status_code=503, detail="Live attendee data could not be loaded"
            ) from error
        global _catalog_ready
        _catalog_ready = True
        _sessions.contexts.clear()
        _sessions.locks.clear()
        return LiveBootstrap(
            existing_schedule=schedule, catalog_sessions=repository.count()
        )


def _ready_repository(request: Request) -> SqliteSessionRepository:
    _require_live(request)
    if not _catalog_ready:
        raise HTTPException(status_code=409, detail="Load live attendee data first")
    return SqliteSessionRepository(_catalog_path)


@router.post("/sessions/recommend", response_model=SearchResults)
def live_recommend(request: Request, query: RecommendationRequest) -> SearchResults:
    service = SessionSearchService(_ready_repository(request))
    return service.search(
        query.query,
        query.filters.to_search_filters(),
        profile=query.profile,
        limit=query.limit,
    )


@router.post("/agent/message", response_model=AgentResponse)
async def live_agent_message(
    request: Request, message: AgentMessageRequest
) -> AgentResponse:
    repository = _ready_repository(request)
    if message.message.casefold().strip().startswith(("confirm", "do it", "go ahead")):
        return AgentResponse(
            status="error",
            message="Live schedule writes are disabled. No changes were made.",
        )
    agent = PathfinderAgent(repository, FakeIntentParser(), events_client=None)
    return await _sessions.handle(
        message.conversation_id,
        message.message,
        agent,
        profile=message.profile,
        current_schedule=message.current_schedule,
    )
