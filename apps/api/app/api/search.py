from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.catalog.search_service import SessionSearchService
from app.catalog.sqlite import SqliteSessionRepository, catalog_db_path
from app.models.profile import AttendeeProfile
from app.ranking.session_search import SearchFilters, SearchResults

router = APIRouter()


class RecommendationFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    levels: list[str] = Field(default_factory=list)
    session_types: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    tracks: list[str] = Field(default_factory=list)

    def to_search_filters(self) -> SearchFilters:
        return SearchFilters(
            levels=tuple(self.levels),
            session_types=tuple(self.session_types),
            services=tuple(self.services),
            topics=tuple(self.topics),
            tracks=tuple(self.tracks),
        )


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=200)
    profile: AttendeeProfile
    filters: RecommendationFilters = Field(default_factory=RecommendationFilters)
    limit: int = Field(default=20, ge=1, le=100)


def get_search_service() -> SessionSearchService:
    return SessionSearchService(SqliteSessionRepository(catalog_db_path()))


@router.get("/sessions/search", response_model=SearchResults)
def search_sessions(
    search_service: Annotated[SessionSearchService, Depends(get_search_service)],
    query: Annotated[str, Query(max_length=200)] = "",
    level: Annotated[list[str] | None, Query()] = None,
    session_type: Annotated[list[str] | None, Query()] = None,
    service: Annotated[list[str] | None, Query()] = None,
    topic: Annotated[list[str] | None, Query()] = None,
    track: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SearchResults:
    filters = SearchFilters(
        levels=tuple(level or ()),
        session_types=tuple(session_type or ()),
        services=tuple(service or ()),
        topics=tuple(topic or ()),
        tracks=tuple(track or ()),
    )
    return search_service.search(query, filters, limit=limit)


@router.post("/sessions/recommend", response_model=SearchResults)
def recommend_sessions(
    request: RecommendationRequest,
    search_service: Annotated[SessionSearchService, Depends(get_search_service)],
) -> SearchResults:
    return search_service.search(
        request.query,
        request.filters.to_search_filters(),
        profile=request.profile,
        limit=request.limit,
    )
