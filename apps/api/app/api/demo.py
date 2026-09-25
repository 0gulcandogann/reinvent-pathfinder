"""Explicitly gated fixture endpoints for the local UI demonstration."""

from fastapi import APIRouter, HTTPException

from app.api.agent import sessions
from app.demo.state import DemoBootstrap, demo_enabled, demo_state

router = APIRouter()


def _require_demo() -> None:
    if not demo_enabled():
        raise HTTPException(status_code=404, detail="Demo mode is disabled")


@router.get("/demo/state", response_model=DemoBootstrap)
async def demo_bootstrap() -> DemoBootstrap:
    _require_demo()
    return await demo_state.ensure()


@router.post("/demo/reset", response_model=DemoBootstrap)
async def reset_demo() -> DemoBootstrap:
    _require_demo()
    result = await demo_state.reset()
    sessions.contexts.clear()
    sessions.locks.clear()
    return result
