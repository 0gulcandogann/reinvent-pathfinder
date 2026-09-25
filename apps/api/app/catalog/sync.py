import json
from dataclasses import dataclass
from pathlib import Path

from app.catalog.normalize import (
    MalformedSessionError,
    normalize_session,
    session_identity,
)
from app.catalog.repository import SessionRepository
from app.clients.events import EventsClient


@dataclass(frozen=True)
class SyncResult:
    fetched: int
    normalized: int
    skipped: int
    errors: int


class CatalogSyncError(RuntimeError):
    """An upstream generation cannot safely replace the local catalog."""


async def sync_catalog(
    client: EventsClient,
    repository: SessionRepository,
    output_path: Path | None = None,
) -> SyncResult:
    """Normalize a full walk, then atomically replace the local generation."""
    sessions = []
    observed_ids: set[str] = set()
    fetched = 0
    skipped = 0
    async for raw_session in client.list_sessions():
        fetched += 1
        if session_id := session_identity(raw_session):
            observed_ids.add(session_id)
        try:
            sessions.append(normalize_session(raw_session))
        except MalformedSessionError:
            skipped += 1

    if fetched and not sessions:
        raise CatalogSyncError(
            "Catalog generation contained no valid sessions; local catalog preserved"
        )

    repository.replace_all(sessions, observed_ids)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_name(output_path.name + ".tmp")
        snapshot = [session.model_dump(mode="json") for session in sessions]
        temporary_path.write_text(
            json.dumps(snapshot, indent=2) + "\n", encoding="utf-8"
        )
        temporary_path.replace(output_path)
    return SyncResult(
        fetched=fetched, normalized=len(sessions), skipped=skipped, errors=0
    )
