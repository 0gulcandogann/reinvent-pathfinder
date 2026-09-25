from app.catalog.repository import SessionRepository
from app.models.profile import AttendeeProfile
from app.ranking.session_search import (
    SearchFilters,
    SearchResults,
    rank_sessions,
)


class SessionSearchService:
    """Search a local repository without reaching AWS."""

    def __init__(self, repository: SessionRepository) -> None:
        self.repository = repository

    def search(
        self,
        query: str = "",
        filters: SearchFilters | None = None,
        *,
        profile: AttendeeProfile | None = None,
        limit: int = 20,
    ) -> SearchResults:
        if limit < 1:
            raise ValueError("limit must be positive")
        hits = rank_sessions(
            self.repository.list_all(), query, filters or SearchFilters(), profile
        )
        return SearchResults(total=len(hits), results=hits[:limit])
