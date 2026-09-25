from collections.abc import AsyncIterator
from typing import Protocol

from app.mutations.models import ReservationResult


class EventsClient(Protocol):
    """Transport-neutral AWS Events catalog, schedule, and mutation contract."""

    def list_sessions(self) -> AsyncIterator[object]: ...

    async def get_schedule(self) -> object: ...

    async def reserve_sessions(self, session_ids: list[str]) -> ReservationResult: ...

    async def cancel_reservation(self, session_id: str) -> None: ...
