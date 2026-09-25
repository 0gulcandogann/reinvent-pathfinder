"""SQLite storage for normalized sessions; no AWS response logic lives here."""

import os
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path

from app.models.session import Session

DEFAULT_DB_PATH = Path(__file__).resolve().parents[4] / "data" / "catalog.sqlite3"
UPSERT_SQL = """
    INSERT INTO sessions (session_id, session_json)
    VALUES (?, ?)
    ON CONFLICT(session_id)
    DO UPDATE SET session_json = excluded.session_json
"""


def catalog_db_path() -> Path:
    configured = os.getenv("PATHFINDER_CATALOG_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    if os.getenv("PATHFINDER_DEMO_MODE", "false").casefold() == "true":
        return DEFAULT_DB_PATH.with_name("demo_catalog.sqlite3")
    return DEFAULT_DB_PATH


class SqliteSessionRepository:
    """One JSON document per session, keyed by the stable AWS session ID."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    session_json TEXT NOT NULL
                )
                """
            )

    def upsert_many(self, sessions: Iterable[Session]) -> int:
        rows = [(session.id, session.model_dump_json()) for session in sessions]
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executemany(UPSERT_SQL, rows)
        return len(rows)

    def replace_all(
        self, sessions: Iterable[Session], observed_ids: Iterable[str] | None = None
    ) -> int:
        """Commit a generation, retaining IDs observed but too malformed to update."""
        rows = [(session.id, session.model_dump_json()) for session in sessions]
        seen = {session_id for session_id, _ in rows}
        if observed_ids is not None:
            seen.update(observed_ids)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TEMP TABLE observed_ids (session_id TEXT PRIMARY KEY)"
            )
            connection.executemany(UPSERT_SQL, rows)
            connection.executemany(
                "INSERT OR IGNORE INTO observed_ids (session_id) VALUES (?)",
                ((session_id,) for session_id in seen),
            )
            connection.execute(
                "DELETE FROM sessions WHERE session_id NOT IN "
                "(SELECT session_id FROM observed_ids)"
            )
        return len(rows)

    def list_all(self) -> list[Session]:
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute(
                "SELECT session_json FROM sessions ORDER BY session_id"
            ).fetchall()
        return [Session.model_validate_json(row[0]) for row in rows]

    def get(self, session_id: str) -> Session | None:
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                "SELECT session_json FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return Session.model_validate_json(row[0]) if row else None

    def count(self) -> int:
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()
        return int(row[0])
