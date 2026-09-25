from collections.abc import Iterable
from typing import Protocol

from app.models.session import Session


class SessionRepository(Protocol):
    """Storage contract for normalized Pathfinder sessions."""

    def upsert_many(self, sessions: Iterable[Session]) -> int: ...

    def replace_all(
        self, sessions: Iterable[Session], observed_ids: Iterable[str] | None = None
    ) -> int: ...

    def list_all(self) -> list[Session]: ...

    def get(self, session_id: str) -> Session | None: ...

    def count(self) -> int: ...
