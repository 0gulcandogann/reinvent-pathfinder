from datetime import datetime

from app.explain.service import explain_schedule
from app.models.profile import AttendeeProfile
from app.models.session import Session
from app.optimizer.solve import optimize_schedule
from app.ranking.session_search import SearchFilters, SearchHit, rank_sessions


def _session(
    session_id: str,
    start_hour: int | None,
    end_hour: int | None,
    *,
    venue: str | None = None,
    title: str | None = None,
    **fields,
) -> Session:
    return Session(
        id=session_id,
        title=title or session_id,
        start_at=(
            datetime(2026, 12, 1, start_hour) if start_hour is not None else None
        ),
        end_at=datetime(2026, 12, 1, end_hour) if end_hour is not None else None,
        venue=venue,
        **fields,
    )


def _hit(
    session: Session,
    score: int,
    *,
    interests: list[str] | None = None,
    goals: list[str] | None = None,
) -> SearchHit:
    matches = {}
    if interests:
        matches["interests"] = interests
    if goals:
        matches["learning_goals"] = goals
    return SearchHit(
        session=session,
        score=score,
        text_score=score,
        matched_preferences=matches,
    )


def test_selected_explanation_preserves_m3_evidence_and_preferences() -> None:
    session = _session(
        "svs401",
        9,
        10,
        title="Advanced serverless observability with AWS Lambda",
        level="400 - Expert",
        services=["AWS Lambda"],
        topics=["Observability"],
    )
    profile = AttendeeProfile(
        interests=["serverless"],
        preferred_services=["AWS Lambda"],
        preferred_topics=["Observability"],
        desired_levels=["400"],
        learning_goals=["observability"],
        prioritize_depth=True,
    )
    hit = rank_sessions(
        [session], "serverless observability", SearchFilters(), profile
    )[0]
    schedule = optimize_schedule([hit], profile)
    explanation = explain_schedule(schedule, profile).sessions[0]
    assert explanation.final_relevance_score == hit.score
    assert explanation.text_relevance_score == hit.text_score
    assert explanation.preference_score == hit.preference_score
    assert explanation.matched_terms == ["serverless", "observability"]
    assert explanation.field_scores == {"title": 24}
    assert explanation.matched_interests == ["serverless"]
    assert explanation.matched_preferred_services == ["AWS Lambda"]
    assert explanation.matched_preferred_topics == ["Observability"]
    assert explanation.matched_desired_levels == ["400"]
    assert explanation.matched_learning_goals == ["observability"]
    assert explanation.depth_bonus == 3
    assert explanation.schedule_fit.blocked_time_clear is True


def test_venue_effect_and_transition_insights() -> None:
    first = _hit(_session("first", 9, 10, venue="Venetian"), 20)
    second = _hit(_session("second", 11, 12, venue="Wynn"), 20)
    profile = AttendeeProfile(minimize_venue_changes=True)
    schedule = optimize_schedule([first, second], profile)
    explained = explain_schedule(schedule, profile)
    effect = explained.sessions[1].venue_effect
    assert effect.transition_from_previous is True
    assert effect.previous_known_venue == "Venetian"
    assert effect.penalty_points == 2
    assert explained.metrics.venue_transitions_per_day == {"2026-12-01": 1}
    assert explained.metrics.total_venue_transitions == 1
    assert any(
        item.code == "venue_transitions" and "Tuesday contains 1" in item.message
        for item in explained.insights
    )


def test_missing_venue_and_optional_metadata_are_safe() -> None:
    hits = [
        _hit(_session("a", 9, 10, venue="Venetian"), 10),
        _hit(_session("b", 11, 12), 10),
        _hit(_session("c", 13, 14, venue="Wynn"), 10),
    ]
    profile = AttendeeProfile(minimize_venue_changes=True)
    explained = explain_schedule(optimize_schedule(hits, profile), profile)
    assert explained.sessions[1].code is None
    assert explained.sessions[1].venue_effect.penalty_points == 0
    assert explained.sessions[2].venue_effect.previous_known_venue == "Venetian"
    assert explained.metrics.total_venue_transitions == 1


def test_time_conflict_and_high_scoring_rejection_explained() -> None:
    a = _hit(_session("A", 10, 12), 100)
    b = _hit(_session("B", 10, 11), 70)
    c = _hit(_session("C", 11, 12), 70)
    profile = AttendeeProfile()
    explained = explain_schedule(optimize_schedule([a, b, c], profile), profile)
    rejected = explained.rejected[0]
    assert rejected.reason == "time_conflict"
    assert rejected.conflicting_session_ids == ["B", "C"]
    assert "B, C" in rejected.message
    assert rejected.important is True
    assert explained.metrics.rejected_high_scoring_conflicts == 1
    assert any(item.code == "high_scoring_conflicts" for item in explained.insights)
    assert explained.sessions[0].displaced_candidates[0].session_id == "A"


def test_blocked_time_rejection_and_usage() -> None:
    profile = AttendeeProfile(
        blocked_times=[{"day": "Tuesday", "start": "13:00", "end": "17:00"}]
    )
    good = _hit(_session("good", 9, 10), 10)
    blocked = _hit(_session("blocked", 14, 15), 50)
    explained = explain_schedule(optimize_schedule([good, blocked], profile), profile)
    assert explained.rejected[0].reason == "blocked_time_conflict"
    assert "blocked time" in explained.rejected[0].message
    usage = explained.metrics.blocked_time_usage
    assert usage.configured_blocks == 1
    assert usage.configured_minutes == 240
    assert usage.excluded_candidate_count == 1


def test_fixed_conflict_rejection_explained() -> None:
    fixed = _session("fixed", 10, 11)
    conflict = _hit(_session("candidate", 10, 11), 30)
    profile = AttendeeProfile()
    schedule = optimize_schedule([conflict], profile, fixed_sessions=[fixed])
    explained = explain_schedule(schedule, profile)
    assert explained.rejected[0].reason == "fixed_session_conflict"
    assert explained.rejected[0].conflicting_session_ids == ["fixed"]
    assert explained.sessions[0].schedule_fit.fixed is True
    assert explained.metrics.fixed_session_count == 1


def test_daily_limit_and_lower_utility_reasons() -> None:
    first = _hit(_session("first", 9, 10), 20)
    second = _hit(_session("second", 11, 12), 10)
    profile = AttendeeProfile(max_sessions_per_day=1)
    explained = explain_schedule(optimize_schedule([first, second], profile), profile)
    assert explained.rejected[0].reason == "daily_limit"
    assert "maximum of 1" in explained.rejected[0].message
    assert explained.metrics.sessions_per_day == {"2026-12-01": 1}
    assert explained.metrics.days_at_daily_limit == ["2026-12-01"]
    assert any(item.code == "daily_limit_reached" for item in explained.insights)

    negative = _hit(_session("negative", 9, 10), -1)
    lower = explain_schedule(
        optimize_schedule([negative], AttendeeProfile()), AttendeeProfile()
    )
    assert lower.rejected[0].reason == "lower_total_schedule_utility"


def test_invalid_time_and_candidate_cap_reasons() -> None:
    good = _hit(_session("good", 9, 10), 20)
    invalid = _hit(_session("invalid", None, None), 30)
    capped = _hit(_session("capped", 11, 12), 5)
    profile = AttendeeProfile()
    schedule = optimize_schedule([good, invalid], profile)
    explained = explain_schedule(
        schedule,
        profile,
        capped_candidates=[capped],
        candidate_total=3,
        candidate_limit=2,
    )
    reasons = {item.session_id: item.reason for item in explained.rejected}
    assert reasons == {"invalid": "invalid_time", "capped": "candidate_cap"}
    assert explained.metrics.candidate_cap_excluded_count == 1
    assert any(item.code == "candidate_cap" for item in explained.insights)


def test_goal_coverage_is_relative_to_eligible_opportunities() -> None:
    goal_a = _hit(_session("A", 9, 10), 10, interests=["serverless"])
    goal_b = _hit(_session("B", 9, 11), 20, interests=["serverless"])
    complementary = _hit(_session("C", 10, 11), 20)
    profile = AttendeeProfile(
        interests=["serverless"], learning_goals=["observability"]
    )
    schedule = optimize_schedule([goal_a, goal_b, complementary], profile)
    assert [item.hit.session.id for item in schedule.selected_sessions] == ["A", "C"]
    coverage = explain_schedule(schedule, profile).goal_coverage
    serverless = coverage["interest:serverless"]
    assert serverless.selected_opportunity_score == 10
    assert serverless.available_opportunity_score == 30
    assert serverless.percentage == 33
    assert serverless.selected_session_ids == ["A"]
    assert coverage["learning_goal:observability"].percentage == 0
    assert coverage["learning_goal:observability"].status == "no_opportunity"


def test_hard_blocked_candidate_is_not_available_goal_opportunity() -> None:
    selected = _hit(_session("selected", 9, 10), 10, interests=["serverless"])
    blocked = _hit(_session("blocked", 14, 15), 50, interests=["serverless"])
    profile = AttendeeProfile(
        interests=["serverless"],
        blocked_times=[{"day": "Tuesday", "start": "13:00", "end": "17:00"}],
    )
    coverage = explain_schedule(
        optimize_schedule([selected, blocked], profile), profile
    ).goal_coverage["interest:serverless"]
    assert coverage.percentage == 100
    assert coverage.available_candidate_count == 1


def test_no_profile_goals_and_no_mutation() -> None:
    profile = AttendeeProfile()
    schedule = optimize_schedule([_hit(_session("one", 9, 10), 10)], profile)
    original = schedule.model_dump(mode="json")
    first = explain_schedule(schedule, profile)
    second = explain_schedule(schedule, profile)
    assert first == second
    assert first.goal_coverage == {}
    assert schedule.model_dump(mode="json") == original
