"""Small in-memory conversation store for local agent demos and API calls."""

import asyncio

from app.agent.models import AgentContext, AgentResponse
from app.agent.service import PathfinderAgent
from app.models.profile import AttendeeProfile
from app.schedule.models import AttendeeSchedule


class InMemoryAgentSessions:
    def __init__(self) -> None:
        self.contexts: dict[str, AgentContext] = {}
        self.locks: dict[str, asyncio.Lock] = {}

    async def handle(
        self,
        conversation_id: str,
        message: str,
        agent: PathfinderAgent,
        *,
        profile: AttendeeProfile | None = None,
        current_schedule: AttendeeSchedule | None = None,
    ) -> AgentResponse:
        lock = self.locks.setdefault(conversation_id, asyncio.Lock())
        async with lock:
            context = self.contexts.setdefault(conversation_id, AgentContext())
            if profile is not None:
                context.profile = profile.model_copy(deep=True)
                context.pending_plan = None
                context.pending_plan_id = None
            if current_schedule is not None:
                context.current_schedule = current_schedule.model_copy(deep=True)
                context.pending_plan = None
                context.pending_plan_id = None
            return await agent.handle(message, context)
