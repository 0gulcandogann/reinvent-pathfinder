from datetime import UTC, date, datetime, timedelta, timezone
from itertools import combinations
from random import Random

import pytest

from app.models.profile import AttendeeProfile
from app.models.session import Session
from app.optimizer.solve import ScheduleConstraintError, optimize_schedule
from app.optimizer.time import SessionInterval, intervals_overlap
from app.ranking.session_search import SearchFilters, SearchHit, rank_sessions

DAY = date(2026, 12, 1)  # Tuesday


def _session(
    session_id: str,
    start_hour: int | None,
    end_hour: int | None,
    *,
    start_minute: int = 0,
    end_minute: int = 0,
    venue: str | None = None,
    title: str | None = None,
    aware: bool = False,
    **fields,
) -> Session:
    zone = UTC if aware else None
    start = (
        datetime(2026, 12, 1, start_hour, start_minute, tzinfo=zone)
        if start_hour is not None
        else None
    )
    end = (
        datetime(2026, 12, 1, end_hour, end_minute, tzinfo=zone)
        if end_hour is not None
        else None
    )
    return Session(
        id=session_id,
        title=title or session_id,
        start_at=start,
        end_at=end,
        venue=venue,
        **fields,
    )


def _hit(session: Session, score: int) -> SearchHit:
    return SearchHit(session=session, score=score, text_score=score)


def _ids(schedule) -> list[str]:
    return [item.hit.session.id for item in schedule.selected_sessions]


def test_overlapping_sessions_never_both_selected() -> None:
    first = _hit(_session("a", 10, 11), 20)
    second = _hit(_session("b", 10, 11, start_minute=30, end_minute=30), 15)
    schedule = optimize_schedule([first, second], AttendeeProfile())
    assert _ids(schedule) == ["a"]
    assert schedule.rejected_sessions[0].reason == "time_conflict"
    assert schedule.rejected_sessions[0].conflicting_with == ["a"]


def test_touching_boundaries_are_compatible() -> None:
    first = _hit(_session("a", 10, 11), 10)
    second = _hit(_session("b", 11, 12), 10)
    schedule = optimize_schedule([first, second], AttendeeProfile())
    assert _ids(schedule) == ["a", "b"]
    assert not intervals_overlap(
        SessionInterval(first.session.start_at, first.session.end_at, DAY),
        SessionInterval(second.session.start_at, second.session.end_at, DAY),
    )


def test_date_specific_limit_reduces_one_day_without_relaxing_global_limit() -> None:
    hits = [
        _hit(_session("a", 9, 10), 20),
        _hit(_session("b", 11, 12), 18),
        _hit(_session("c", 14, 15), 16),
    ]
    profile = AttendeeProfile(max_sessions_per_day=2)
    lighter = optimize_schedule(hits, profile, daily_limits={DAY: 1})
    assert _ids(lighter) == ["a"]
    assert lighter.constraints.daily_limits == {DAY.isoformat(): 1}
    cannot_relax = optimize_schedule(hits, profile, daily_limits={DAY: 5})
    assert len(cannot_relax.selected_sessions) == 2


def test_global_abc_optimization_beats_greedy_choice() -> None:
    a = _hit(_session("A", 10, 12), 100)
    b = _hit(_session("B", 10, 11), 70)
    c = _hit(_session("C", 11, 12), 70)
    schedule = optimize_schedule([a, b, c], AttendeeProfile())
    assert _ids(schedule) == ["B", "C"]
    assert schedule.score == 140
    assert schedule.rejected_sessions[0].hit.session.id == "A"
    assert schedule.rejected_sessions[0].conflicting_with == ["B", "C"]
    assert schedule.alternatives == {}


def test_blocked_time_is_hard_constraint() -> None:
    profile = AttendeeProfile(
        blocked_times=[{"day": "Tuesday", "start": "13:00", "end": "17:00"}]
    )
    blocked = _hit(_session("blocked", 12, 14), 100)
    before = _hit(_session("before", 11, 13), 10)
    after = _hit(_session("after", 17, 18), 10)
    schedule = optimize_schedule([blocked, before, after], profile)
    assert _ids(schedule) == ["before", "after"]
    assert (
        next(
            item.reason
            for item in schedule.rejected_sessions
            if item.hit.session.id == "blocked"
        )
        == "blocked_time_conflict"
    )


def test_max_sessions_per_day_is_hard_constraint() -> None:
    hits = [_hit(_session(str(hour), hour, hour + 1), 10) for hour in (9, 11, 13)]
    schedule = optimize_schedule(hits, AttendeeProfile(max_sessions_per_day=2))
    assert len(schedule.selected_sessions) == 2
    assert schedule.sessions_per_day == {"2026-12-01": 2}
    assert any(item.reason == "daily_limit" for item in schedule.rejected_sessions)
    assert "Tuesday reached the configured maximum of 2 sessions." in schedule.warnings


def test_fixed_session_preserved_and_conflicts_rejected() -> None:
    fixed = _session("fixed", 10, 11, venue="Venetian")
    conflict = _hit(_session("conflict", 10, 11, start_minute=30, end_minute=30), 100)
    later = _hit(_session("later", 11, 12), 10)
    schedule = optimize_schedule(
        [conflict, later], AttendeeProfile(), fixed_sessions=[fixed]
    )
    assert _ids(schedule) == ["fixed", "later"]
    assert schedule.selected_sessions[0].fixed is True
    assert schedule.selected_sessions[0].selection_reason == "fixed_session"
    assert schedule.rejected_sessions[0].reason == "fixed_session_conflict"
    assert schedule.rejected_sessions[0].conflicting_with == ["fixed"]


def test_fixed_session_counts_toward_daily_limit_across_gaps() -> None:
    fixed = _session("fixed", 11, 12)
    before = _hit(_session("before", 9, 10), 20)
    after = _hit(_session("after", 13, 14), 30)
    schedule = optimize_schedule(
        [before, after],
        AttendeeProfile(max_sessions_per_day=2),
        fixed_sessions=[fixed],
    )
    assert _ids(schedule) == ["fixed", "after"]
    assert schedule.rejected_sessions[0].reason == "daily_limit"


@pytest.mark.parametrize("violation", ["overlap", "blocked", "daily_limit", "time"])
def test_invalid_fixed_schedule_fails_explicitly(violation: str) -> None:
    fixed = _session("fixed", 10, 11)
    profile = AttendeeProfile()
    fixed_sessions = [fixed]
    if violation == "overlap":
        fixed_sessions.append(_session("other", 10, 11))
    elif violation == "blocked":
        profile = AttendeeProfile(
            blocked_times=[{"day": "Tuesday", "start": "09:00", "end": "12:00"}]
        )
    elif violation == "daily_limit":
        profile.max_sessions_per_day = 1
        fixed_sessions.append(_session("other", 11, 12))
    else:
        fixed_sessions = [_session("fixed", None, None)]
    with pytest.raises(ScheduleConstraintError):
        optimize_schedule([], profile, fixed_sessions=fixed_sessions)


def test_venue_penalty_changes_near_equivalent_choice() -> None:
    first = _hit(_session("first", 9, 10, venue="Venetian"), 10)
    same = _hit(_session("same", 11, 12, venue="Venetian"), 10)
    away = _hit(_session("away", 11, 12, venue="Wynn"), 11)
    with_preference = optimize_schedule(
        [first, same, away], AttendeeProfile(minimize_venue_changes=True)
    )
    without_preference = optimize_schedule(
        [first, same, away], AttendeeProfile(minimize_venue_changes=False)
    )
    assert _ids(with_preference) == ["first", "same"]
    assert with_preference.venue_penalty == 0
    assert _ids(without_preference) == ["first", "away"]
    assert without_preference.venue_transitions == 1
    assert without_preference.venue_penalty == 0


def test_missing_venue_creates_no_transition_penalty() -> None:
    first = _hit(_session("first", 9, 10, venue=None), 10)
    next_session = _hit(_session("next", 11, 12, venue="Wynn"), 10)
    schedule = optimize_schedule(
        [first, next_session], AttendeeProfile(minimize_venue_changes=True)
    )
    assert _ids(schedule) == ["first", "next"]
    assert schedule.venue_transitions == 0
    assert schedule.venue_penalty == 0


def test_fixed_session_contributes_to_venue_transition() -> None:
    fixed = _session("fixed", 9, 10, venue="Venetian")
    candidate = _hit(_session("candidate", 11, 12, venue="Wynn"), 10)
    schedule = optimize_schedule(
        [candidate],
        AttendeeProfile(minimize_venue_changes=True),
        fixed_sessions=[fixed],
    )
    assert _ids(schedule) == ["fixed", "candidate"]
    assert schedule.venue_transitions == 1
    assert schedule.venue_penalty == 2
    assert schedule.score == 8


def test_missing_invalid_and_cross_day_times_are_rejected() -> None:
    good = _hit(_session("good", 9, 10), 10)
    missing = _hit(_session("missing", None, None), 50)
    backwards = _hit(_session("backwards", 12, 11), 50)
    cross_day = _hit(
        _session("cross", 23, 23).model_copy(
            update={"end_at": datetime(2026, 12, 2, 1)}
        ),
        50,
    )
    schedule = optimize_schedule(
        [good, missing, backwards, cross_day], AttendeeProfile()
    )
    assert _ids(schedule) == ["good"]
    reasons = {item.hit.session.id: item.reason for item in schedule.rejected_sessions}
    assert reasons == {
        "missing": "invalid_time",
        "backwards": "invalid_time",
        "cross": "cross_day_session",
    }


def test_timezone_awareness_is_preserved_and_not_mixed() -> None:
    aware = _hit(_session("aware", 9, 10, aware=True), 10)
    naive = _hit(_session("naive", 11, 12), 10)
    schedule = optimize_schedule([aware, naive], AttendeeProfile())
    assert _ids(schedule) == ["aware"]
    assert schedule.selected_sessions[0].hit.session.start_at.tzinfo is UTC
    assert schedule.rejected_sessions[0].reason == "timezone_mismatch"
    with pytest.raises(ScheduleConstraintError, match="timezone_mismatch"):
        optimize_schedule(
            [], AttendeeProfile(), fixed_sessions=[aware.session, naive.session]
        )


def test_invalid_aware_candidate_does_not_set_event_timezone() -> None:
    invalid = _hit(_session("invalid", 9, None, aware=True), 100)
    valid = _hit(_session("valid", 10, 11), 10)
    schedule = optimize_schedule([invalid, valid], AttendeeProfile())
    assert _ids(schedule) == ["valid"]
    assert schedule.rejected_sessions[0].reason == "invalid_time"


def test_date_window_rejects_outside_candidates() -> None:
    hit = _hit(_session("outside", 9, 10), 10)
    schedule = optimize_schedule(
        [hit], AttendeeProfile(), event_start=date(2026, 12, 2)
    )
    assert schedule.selected_sessions == []
    assert schedule.rejected_sessions[0].reason == "outside_event_dates"


def test_deterministic_output_and_alternative_replacement() -> None:
    primary = _hit(_session("primary", 10, 11), 20)
    backup = _hit(_session("backup", 10, 11), 15)
    inputs = [primary, backup]
    first = optimize_schedule(inputs, AttendeeProfile())
    second = optimize_schedule(list(reversed(inputs)), AttendeeProfile())
    assert first == second
    assert first.alternatives["primary"][0].hit.session.id == "backup"
    assert first.alternatives["primary"][0].rejected_reason == "time_conflict"


def test_m3_preference_scores_affect_optimizer_choice() -> None:
    plain = _session("a", 10, 11, title="Serverless patterns")
    preferred = _session(
        "b", 10, 11, title="Serverless patterns", services=["AWS Lambda"]
    )
    baseline = rank_sessions([plain, preferred], "serverless", SearchFilters())
    profile = AttendeeProfile(preferred_services=["AWS Lambda"])
    personalized = rank_sessions(
        [plain, preferred], "serverless", SearchFilters(), profile
    )
    assert _ids(optimize_schedule(baseline, AttendeeProfile())) == ["a"]
    assert _ids(optimize_schedule(personalized, profile)) == ["b"]
    assert personalized[0].preference_score == 5


def test_aware_datetimes_in_different_offsets_compare_correctly() -> None:
    utc = UTC
    plus_two = timezone(timedelta(hours=2))
    first = _hit(
        Session(
            id="first",
            title="first",
            start_at=datetime(2026, 12, 1, 10, tzinfo=utc),
            end_at=datetime(2026, 12, 1, 11, tzinfo=utc),
        ),
        10,
    )
    second = _hit(
        Session(
            id="second",
            title="second",
            start_at=datetime(2026, 12, 1, 13, tzinfo=plus_two),
            end_at=datetime(2026, 12, 1, 14, tzinfo=plus_two),
        ),
        10,
    )
    schedule = optimize_schedule([first, second], AttendeeProfile())
    assert _ids(schedule) == ["first", "second"]


def test_small_cases_match_exhaustive_global_objective() -> None:
    for seed in range(12):
        random = Random(seed)
        hits = []
        for index in range(8):
            start = random.randrange(9, 16)
            duration = random.choice((1, 2))
            venue = random.choice(("Venetian", "Wynn", None))
            hits.append(
                _hit(
                    _session(str(index), start, start + duration, venue=venue),
                    random.randrange(1, 21),
                )
            )
        profile = AttendeeProfile(max_sessions_per_day=3, minimize_venue_changes=True)
        optimized = optimize_schedule(hits, profile)
        exhaustive_best = 0
        for count in range(1, 4):
            for subset in combinations(hits, count):
                ordered = sorted(subset, key=lambda hit: hit.session.start_at)
                if any(
                    first.session.end_at > second.session.start_at
                    for first, second in zip(ordered, ordered[1:], strict=False)
                ):
                    continue
                known_venues = [
                    hit.session.venue for hit in ordered if hit.session.venue
                ]
                transitions = sum(
                    first != second
                    for first, second in zip(
                        known_venues, known_venues[1:], strict=False
                    )
                )
                utility = sum(hit.score for hit in ordered) - 2 * transitions
                exhaustive_best = max(exhaustive_best, utility)
        assert optimized.score == exhaustive_best
