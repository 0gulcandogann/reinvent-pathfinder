"""Thin HTTP boundary for side-effect-free plans and confirmed execution."""

import os
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.catalog.sqlite import SqliteSessionRepository, catalog_db_path
from app.clients.events import EventsClient
from app.clients.events_api import AwsEventsRestClient
from app.demo.state import demo_enabled
from app.mutations.executor import MutationExecutionError, MutationExecutor
from app.mutations.models import (
    MutationExecutionResult,
    Replacement,
    ScheduleMutationPlan,
)
from app.mutations.planner import MutationPlanError, MutationPlanner
from app.optimizer.models import OptimizedSchedule
from app.schedule.models import AttendeeSchedule

router = APIRouter()


class MutationPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_schedule: AttendeeSchedule
    optimized_schedule: OptimizedSchedule
    remove_session_ids: list[str] = Field(default_factory=list)
    replacements: list[Replacement] = Field(default_factory=list)


class MutationExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: ScheduleMutationPlan
    confirmed: bool = False


def get_mutation_planner() -> MutationPlanner:
    return MutationPlanner(SqliteSessionRepository(catalog_db_path()))


async def get_write_client() -> AsyncIterator[EventsClient | None]:
    if demo_enabled():
        yield None
        return
    if os.getenv("AWS_EVENTS_ENABLE_WRITES", "false").casefold() != "true":
        yield None
        return
    token = os.getenv("AWS_EVENTS_ACCESS_TOKEN", "")
    if not token.strip():
        raise HTTPException(
            status_code=503, detail="AWS Events write token unavailable"
        )
    async with AwsEventsRestClient(token, enable_writes=True) as client:
        yield client


@router.post("/schedule/mutations/plan", response_model=ScheduleMutationPlan)
def plan_mutations(
    request: MutationPlanRequest,
    planner: Annotated[MutationPlanner, Depends(get_mutation_planner)],
) -> ScheduleMutationPlan:
    try:
        return planner.build(
            request.current_schedule,
            request.optimized_schedule,
            remove_session_ids=request.remove_session_ids,
            replacements=request.replacements,
        )
    except MutationPlanError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/schedule/mutations/execute", response_model=MutationExecutionResult)
async def execute_mutations(
    request: MutationExecuteRequest,
    client: Annotated[EventsClient | None, Depends(get_write_client)],
) -> MutationExecutionResult:
    try:
        return await MutationExecutor(client).execute(
            request.plan, confirmed=request.confirmed
        )
    except MutationExecutionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
