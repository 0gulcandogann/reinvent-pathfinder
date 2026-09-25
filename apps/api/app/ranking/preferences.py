"""Explainable, deterministic attendee preference scoring."""

import re
from dataclasses import dataclass, field

from app.models.profile import AttendeeProfile
from app.models.session import Session

INTEREST_MATCH_WEIGHT = 4
PREFERRED_SERVICE_WEIGHT = 5
PREFERRED_TOPIC_WEIGHT = 4
DESIRED_LEVEL_WEIGHT = 3
AVOIDED_LEVEL_PENALTY = -6
PREFERRED_SESSION_TYPE_WEIGHT = 3
LEARNING_GOAL_WEIGHT = 4
MAX_INTEREST_MATCHES = 2
MAX_LEARNING_GOAL_MATCHES = 2
DEPTH_BONUSES = {"300": 1, "400": 3}

TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
LEVEL_PATTERN = re.compile(r"\b[1-4]00\b")


@dataclass(frozen=True)
class PreferenceScore:
    score: int = 0
    contributions: dict[str, int] = field(default_factory=dict)
    matched_preferences: dict[str, list[str]] = field(default_factory=dict)
    penalties: dict[str, int] = field(default_factory=dict)


def depth_bonus(level: str | None) -> int:
    """Only explicit 300/400 levels count as advanced."""
    if not level:
        return 0
    match = LEVEL_PATTERN.search(level)
    return DEPTH_BONUSES.get(match.group() if match else "", 0)


def score_preferences(
    session: Session,
    profile: AttendeeProfile,
    field_tokens: dict[str, set[str]],
) -> PreferenceScore:
    """Score visible preferences; schedule-only profile fields are ignored."""
    contributions: dict[str, int] = {}
    matched: dict[str, list[str]] = {}
    penalties: dict[str, int] = {}
    searchable_tokens = set().union(*field_tokens.values())

    interests = _matched_phrases(profile.interests, searchable_tokens)
    if interests:
        matched["interests"] = interests
        contributions["interests"] = (
            min(len(interests), MAX_INTEREST_MATCHES) * INTEREST_MATCH_WEIGHT
        )

    services = _matched_values(profile.preferred_services, session.services)
    if services:
        matched["preferred_services"] = services
        contributions["preferred_services"] = PREFERRED_SERVICE_WEIGHT

    topics = _matched_values(profile.preferred_topics, session.topics)
    if topics:
        matched["preferred_topics"] = topics
        contributions["preferred_topics"] = PREFERRED_TOPIC_WEIGHT

    desired_levels = _matched_levels(profile.desired_levels, session.level)
    if desired_levels:
        matched["desired_levels"] = desired_levels
        contributions["desired_levels"] = DESIRED_LEVEL_WEIGHT

    avoided_levels = _matched_levels(profile.avoided_levels, session.level)
    if avoided_levels:
        matched["avoided_levels"] = avoided_levels
        penalties["avoided_levels"] = AVOIDED_LEVEL_PENALTY

    session_types = _matched_values(
        profile.preferred_session_types, [session.session_type or ""]
    )
    if session_types:
        matched["preferred_session_types"] = session_types
        contributions["preferred_session_types"] = PREFERRED_SESSION_TYPE_WEIGHT

    goals = _matched_phrases(profile.learning_goals, searchable_tokens)
    if goals:
        matched["learning_goals"] = goals
        contributions["learning_goals"] = (
            min(len(goals), MAX_LEARNING_GOAL_MATCHES) * LEARNING_GOAL_WEIGHT
        )

    if profile.prioritize_depth:
        bonus = depth_bonus(session.level)
        if bonus:
            contributions["prioritize_depth"] = bonus

    return PreferenceScore(
        score=sum(contributions.values()) + sum(penalties.values()),
        contributions=contributions,
        matched_preferences=matched,
        penalties=penalties,
    )


def _matched_phrases(values: list[str], tokens: set[str]) -> list[str]:
    matches = []
    seen: set[tuple[str, ...]] = set()
    for value in values:
        phrase_tokens = tuple(TOKEN_PATTERN.findall(value.casefold()))
        if phrase_tokens and phrase_tokens not in seen:
            seen.add(phrase_tokens)
            if set(phrase_tokens).issubset(tokens):
                matches.append(value)
    return matches


def _matched_values(wanted: list[str], actual: list[str]) -> list[str]:
    actual_values = {value.strip().casefold() for value in actual}
    matches = []
    seen: set[str] = set()
    for value in wanted:
        normalized = value.strip().casefold()
        if normalized and normalized not in seen:
            seen.add(normalized)
            if normalized in actual_values:
                matches.append(value)
    return matches


def _matched_levels(wanted: list[str], level: str | None) -> list[str]:
    if not level:
        return []
    normalized = level.strip().casefold()
    level_codes = set(LEVEL_PATTERN.findall(normalized))
    matches = []
    for value in wanted:
        choice = value.strip().casefold()
        codes = set(LEVEL_PATTERN.findall(choice))
        if choice and (
            choice == normalized or (codes and codes.intersection(level_codes))
        ):
            matches.append(value)
    return matches
