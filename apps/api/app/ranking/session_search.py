"""Pure Python token matching and ranking for the local catalog."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.models.profile import AttendeeProfile
from app.models.session import Session
from app.ranking.preferences import score_preferences

TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
FIELD_WEIGHTS = (
    ("title", 12),
    ("services", 8),
    ("topics", 8),
    ("tracks", 5),
    ("roles", 5),
    ("abstract", 2),
    ("speakers", 1),
)


@dataclass(frozen=True)
class SearchFilters:
    levels: tuple[str, ...] = ()
    session_types: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    tracks: tuple[str, ...] = ()


class SearchHit(BaseModel):
    session: Session
    score: int
    text_score: int = 0
    preference_score: int = 0
    matched_terms: list[str] = Field(default_factory=list)
    field_scores: dict[str, int] = Field(default_factory=dict)
    preference_contributions: dict[str, int] = Field(default_factory=dict)
    matched_preferences: dict[str, list[str]] = Field(default_factory=dict)
    penalties: dict[str, int] = Field(default_factory=dict)


class SearchResults(BaseModel):
    total: int
    results: list[SearchHit]


def rank_sessions(
    sessions: Iterable[Session],
    query: str,
    filters: SearchFilters,
    profile: AttendeeProfile | None = None,
) -> list[SearchHit]:
    """Score each unique query token once, using its strongest matching field."""
    terms = list(dict.fromkeys(_tokens(query)))
    choices = {
        "levels": _choices(filters.levels),
        "session_types": _choices(filters.session_types),
        "services": _choices(filters.services),
        "topics": _choices(filters.topics),
        "tracks": _choices(filters.tracks),
    }
    hits: list[SearchHit] = []
    for session in sessions:
        if not _passes_filters(session, choices):
            continue
        field_tokens = {
            "title": set(_tokens(session.title)),
            "services": set(_tokens(" ".join(session.services))),
            "topics": set(_tokens(" ".join(session.topics))),
            "tracks": set(_tokens(" ".join(session.tracks))),
            "roles": set(_tokens(" ".join(session.roles))),
            "abstract": set(_tokens(session.abstract or "")),
            "speakers": set(_tokens(" ".join(session.speakers))),
        }
        field_scores: dict[str, int] = {}
        matched_terms: list[str] = []
        for term in terms:
            for field, weight in FIELD_WEIGHTS:
                if term in field_tokens[field]:
                    field_scores[field] = field_scores.get(field, 0) + weight
                    matched_terms.append(term)
                    break
        if terms and not matched_terms:
            continue
        text_score = sum(field_scores.values())
        preference = (
            score_preferences(session, profile, field_tokens) if profile else None
        )
        hits.append(
            SearchHit(
                session=session,
                score=text_score + (preference.score if preference else 0),
                text_score=text_score,
                preference_score=preference.score if preference else 0,
                matched_terms=matched_terms,
                field_scores=field_scores,
                preference_contributions=(
                    preference.contributions if preference else {}
                ),
                matched_preferences=(
                    preference.matched_preferences if preference else {}
                ),
                penalties=preference.penalties if preference else {},
            )
        )
    hits.sort(
        key=lambda hit: (-hit.score, hit.session.title.casefold(), hit.session.id)
    )
    return hits


def _tokens(value: str) -> list[str]:
    return TOKEN_PATTERN.findall(value.casefold())


def _choices(values: tuple[str, ...]) -> set[str]:
    return {
        choice.strip().casefold()
        for value in values
        for choice in value.split(",")
        if choice.strip()
    }


def _passes_filters(session: Session, choices: dict[str, set[str]]) -> bool:
    level = (session.level or "").casefold()
    if choices["levels"] and not (
        level in choices["levels"] or choices["levels"].intersection(_tokens(level))
    ):
        return False
    if choices["session_types"] and (
        (session.session_type or "").casefold() not in choices["session_types"]
    ):
        return False
    for field in ("services", "topics", "tracks"):
        wanted = choices[field]
        if wanted and not wanted.intersection(
            value.casefold() for value in getattr(session, field)
        ):
            return False
    return True
