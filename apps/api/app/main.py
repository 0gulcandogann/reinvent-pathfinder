from fastapi import FastAPI

from app.api.agent import router as agent_router
from app.api.auth import router as auth_router
from app.api.demo import router as demo_router
from app.api.existing_schedule import router as existing_schedule_router
from app.api.mutations import router as mutations_router
from app.api.schedule import router as schedule_router
from app.api.search import router as search_router

app = FastAPI(title="re:Invent Pathfinder")
app.include_router(search_router)
app.include_router(schedule_router)
app.include_router(existing_schedule_router)
app.include_router(mutations_router)
app.include_router(agent_router)
app.include_router(auth_router)
app.include_router(demo_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
