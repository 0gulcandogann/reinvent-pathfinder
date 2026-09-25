"""Thin local UI boundary for the existing Builder ID OAuth helper."""

from fastapi import APIRouter, HTTPException, Request, Response

from app.auth.connection import BuilderIdConnection, BuilderIdStart, BuilderIdStatus

router = APIRouter()
connection = BuilderIdConnection()
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@router.get(
    "/auth/builder-id/status",
    response_model=BuilderIdStatus,
    response_model_exclude_none=True,
)
def builder_id_status(response: Response) -> BuilderIdStatus:
    response.headers["Cache-Control"] = "no-store"
    return connection.status()


@router.post(
    "/auth/builder-id/start",
    response_model=BuilderIdStart,
    response_model_exclude_none=True,
    status_code=202,
)
async def start_builder_id_login(
    request: Request, response: Response
) -> BuilderIdStart:
    if (
        request.url.hostname not in _LOOPBACK
        or request.client is None
        or request.client.host not in _LOOPBACK
    ):
        raise HTTPException(status_code=403, detail="Local sign-in is unavailable")
    response.headers["Cache-Control"] = "no-store"
    return await connection.start()


@router.post(
    "/auth/builder-id/recheck",
    response_model=BuilderIdStatus,
    response_model_exclude_none=True,
)
async def recheck_builder_id_access(
    request: Request, response: Response
) -> BuilderIdStatus:
    if (
        request.url.hostname not in _LOOPBACK
        or request.client is None
        or request.client.host not in _LOOPBACK
    ):
        raise HTTPException(
            status_code=403, detail="Local attendee check is unavailable"
        )
    response.headers["Cache-Control"] = "no-store"
    return await connection.recheck()
