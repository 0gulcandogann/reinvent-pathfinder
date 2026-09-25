"""Thin natural-language message endpoint over the Pathfinder agent service."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.agent.context import InMemoryAgentSessions
from app.agent.models import AgentResponse
from app.agent.parser import FakeIntentParser
from app.agent.service import PathfinderAgent
from app.catalog.sqlite import SqliteSessionRepository, catalog_db_path
from app.demo.state import demo_enabled, demo_state
from app.models.profile import AttendeeProfile
from app.schedule.models import AttendeeSchedule

router = APIRouter()
sessions = InMemoryAgentSessions()


class AgentMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str = Field(min_length=1, max_length=100)
    profile: AttendeeProfile | None = None
    current_schedule: AttendeeSchedule | None = None


async def get_pathfinder_agent() -> PathfinderAgent:
    fake = None
    if demo_enabled():
        await demo_state.ensure()
        fake = demo_state.fake
    return PathfinderAgent(
        SqliteSessionRepository(catalog_db_path()), FakeIntentParser(), fake
    )


@router.post("/agent/message", response_model=AgentResponse)
async def agent_message(
    request: AgentMessageRequest,
    agent: Annotated[PathfinderAgent, Depends(get_pathfinder_agent)],
) -> AgentResponse:
    return await sessions.handle(
        request.conversation_id,
        request.message,
        agent,
        profile=request.profile,
        current_schedule=request.current_schedule,
    )
