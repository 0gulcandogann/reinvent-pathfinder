import json
from pathlib import Path

import pytest

from app.catalog.normalize import normalize_session
from app.models.profile import AttendeeProfile
from app.ranking.preferences import depth_bonus
from app.ranking.session_search import SearchFilters, rank_sessions

ROOT = Path(__file__).resolve().parents[3]


def _session(**overrides):
    raw = {
        "sessionId": "test",
        "title": "AWS Lambda architecture",
        "abstract": "Build event-driven systems with practical patterns.",
        "level": "300 - Advanced",
        "type": "Workshop",
        "services": ["AWS Lambda"],
        "topics": ["Serverless"],
    }
    raw.update(overrides)
    return normalize_session(raw)


def _hit(profile: AttendeeProfile):
    return rank_sessions([_session()], "lambda", SearchFilters(), profile)[0]


def test_profile_defaults_and_independent_lists() -> None:
    first = AttendeeProfile()
    second = AttendeeProfile()
    first.interests.append("serverless")
    assert second.interests == []
    assert first.blocked_times == []
    assert first.max_sessions_per_day is None
    assert first.minimize_venue_changes is False
    assert first.prioritize_depth is False
    assert first.diversity_weight == 0.0


@pytest.mark.parametrize(
    ("profile_data", "category", "expected"),
    [
        ({"interests": ["event-driven"]}, "interests", 4),
        ({"preferred_services": ["aws lambda"]}, "preferred_services", 5),
        ({"preferred_topics": ["serverless"]}, "preferred_topics", 4),
        ({"desired_levels": ["300"]}, "desired_levels", 3),
        (
            {"preferred_session_types": ["workshop"]},
            "preferred_session_types",
            3,
        ),
        ({"learning_goals": ["event-driven systems"]}, "learning_goals", 4),
    ],
)
def test_positive_preference_contributions(profile_data, category, expected) -> None:
    hit = _hit(AttendeeProfile(**profile_data))
    assert hit.preference_contributions[category] == expected
    assert hit.preference_score == expected
    assert hit.matched_preferences[category]
    assert hit.score == hit.text_score + hit.preference_score


def test_avoided_level_is_an_explained_penalty() -> None:
    hit = _hit(AttendeeProfile(avoided_levels=["300"]))
    assert hit.penalties == {"avoided_levels": -6}
    assert hit.matched_preferences["avoided_levels"] == ["300"]
    assert hit.preference_score == -6


def test_duplicate_preferences_do_not_inflate_score() -> None:
    hit = _hit(
        AttendeeProfile(
            interests=["Lambda", "lambda"], preferred_services=["AWS Lambda"]
        )
    )
    assert hit.preference_contributions["interests"] == 4
    assert hit.matched_preferences["interests"] == ["Lambda"]


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        ("400 - Expert", 3),
        ("300 - Advanced", 1),
        ("200 - Intermediate", 0),
        ("100 - Foundational", 0),
        ("Advanced", 0),
        (None, 0),
    ],
)
def test_depth_bonus_requires_explicit_advanced_level(level, expected) -> None:
    assert depth_bonus(level) == expected
    session = _session(level=level)
    hit = rank_sessions(
        [session], "lambda", SearchFilters(), AttendeeProfile(prioritize_depth=True)
    )[0]
    assert hit.preference_contributions.get("prioritize_depth", 0) == expected


def test_no_profile_preserves_text_order_and_scores() -> None:
    title = normalize_session({"sessionId": "title", "title": "Lambda patterns"})
    abstract = normalize_session(
        {"sessionId": "abstract", "title": "Runtime patterns", "abstract": "Lambda"}
    )
    hits = rank_sessions([abstract, title], "lambda", SearchFilters())
    assert [hit.session.id for hit in hits] == ["title", "abstract"]
    assert [hit.score for hit in hits] == [12, 2]
    assert all(
        hit.score == hit.text_score and hit.preference_score == 0 for hit in hits
    )


def test_profile_reorders_similar_text_matches() -> None:
    plain = normalize_session({"sessionId": "a", "title": "Lambda basics"})
    favored = normalize_session(
        {"sessionId": "b", "title": "Lambda operations", "services": ["AWS Lambda"]}
    )
    without = rank_sessions([plain, favored], "lambda", SearchFilters())
    with_profile = rank_sessions(
        [plain, favored],
        "lambda",
        SearchFilters(),
        AttendeeProfile(preferred_services=["AWS Lambda"]),
    )
    assert [hit.session.id for hit in without] == ["a", "b"]
    assert [hit.session.id for hit in with_profile] == ["b", "a"]


def test_one_minor_preference_does_not_overcome_strong_text_relevance() -> None:
    strong = normalize_session(
        {"sessionId": "strong", "title": "Advanced serverless architecture"}
    )
    weak = normalize_session(
        {
            "sessionId": "weak",
            "title": "Other topic",
            "abstract": "Advanced serverless architecture",
            "services": ["AWS Lambda"],
        }
    )
    hits = rank_sessions(
        [weak, strong],
        "advanced serverless architecture",
        SearchFilters(),
        AttendeeProfile(preferred_services=["AWS Lambda"]),
    )
    assert [hit.session.id for hit in hits] == ["strong", "weak"]
    assert hits[0].text_score == 36
    assert hits[1].text_score == 6
    assert hits[1].preference_score == 5


def test_future_schedule_fields_do_not_change_m3_ranking() -> None:
    session = _session()
    baseline = rank_sessions([session], "lambda", SearchFilters(), AttendeeProfile())
    future = AttendeeProfile(
        blocked_times=[{"day": "Tuesday", "start": "12:00", "end": "17:00"}],
        max_sessions_per_day=1,
        minimize_venue_changes=True,
        diversity_weight=1.0,
    )
    with_future_fields = rank_sessions([session], "lambda", SearchFilters(), future)
    assert with_future_fields[0].score == baseline[0].score


def test_personas_rank_different_sessions_first(raw_sessions) -> None:
    sessions = [normalize_session(raw) for raw in raw_sessions]
    personas = json.loads(
        (ROOT / "data" / "fixtures" / "personas.json").read_text(encoding="utf-8")
    )
    top_codes = {
        name: rank_sessions(
            sessions, "serverless", SearchFilters(), AttendeeProfile(**profile)
        )[0].session.code
        for name, profile in personas.items()
    }
    assert top_codes == {
        "Serverless Engineer": "SVS401",
        "Security Engineer": "SEC330",
        "New AWS User": "SVS101",
    }
