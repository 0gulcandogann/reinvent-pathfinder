"""Global per-day schedule optimization using a weighted interval DAG."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, tzinfo

from app.models.profile import WEEKDAY_NAMES, AttendeeProfile
from app.models.session import Session
from app.optimizer.models import (
    AppliedConstraints,
    OptimizedSchedule,
    RejectedSession,
    ScheduleAlternative,
    ScheduledSession,
)
from app.optimizer.time import (
    SessionInterval,
    blocked_time_overlaps,
    intervals_overlap,
    is_aware,
    session_interval,
)
from app.ranking.session_search import SearchHit

VENUE_TRANSITION_PENALTY = 2
MAX_ALTERNATIVES_PER_SESSION = 3


class ScheduleConstraintError(ValueError):
    """Fixed sessions or explicit constraints cannot form a valid itinerary."""


@dataclass(frozen=True)
class _Candidate:
    hit: SearchHit
    interval: SessionInterval
    fixed: bool = False

    @property
    def id(self) -> str:
        return self.hit.session.id

    @property
    def venue(self) -> str | None:
        value = self.hit.session.venue
        return value.strip().casefold() if value and value.strip() else None


@dataclass(frozen=True)
class _Plan:
    score: int = 0
    relevance_total: int = 0
    transitions: int = 0
    indices: tuple[int, ...] = ()
    ids: tuple[str, ...] = ()
    last_known_venue: str | None = None


def optimize_schedule(
    candidates: Iterable[SearchHit],
    profile: AttendeeProfile,
    *,
    fixed_sessions: Iterable[Session] = (),
    event_start: date | None = None,
    event_end: date | None = None,
    daily_limits: dict[date, int] | None = None,
) -> OptimizedSchedule:
    """Maximize M3 utility across each event day under hard constraints."""
    if event_start and event_end and event_end < event_start:
        raise ScheduleConstraintError("event_end must not precede event_start")
    if profile.max_sessions_per_day is not None and profile.max_sessions_per_day < 1:
        raise ScheduleConstraintError("max_sessions_per_day must be positive")
    daily_limits = daily_limits or {}
    if any(limit < 1 for limit in daily_limits.values()):
        raise ScheduleConstraintError("daily limits must be positive")

    hits = list(candidates)
    fixed = list(fixed_sessions)
    fixed_ids = [session.id for session in fixed]
    if len(fixed_ids) != len(set(fixed_ids)):
        raise ScheduleConstraintError("fixed session IDs must be unique")

    expect_aware, event_timezone = _time_mode(hits, fixed)
    best_hits = _unique_hits(hits)
    fixed_items = _prepare_fixed(
        fixed,
        best_hits,
        profile,
        expect_aware,
        event_timezone,
        event_start,
        event_end,
    )
    _validate_fixed(fixed_items, profile, daily_limits)
    fixed_id_set = set(fixed_ids)

    rejected: list[RejectedSession] = []
    eligible: list[_Candidate] = []
    for hit in best_hits.values():
        if hit.session.id in fixed_id_set:
            continue
        interval, reason = session_interval(
            hit.session, expect_aware=expect_aware, event_timezone=event_timezone
        )
        if reason or interval is None:
            rejected.append(RejectedSession(hit=hit, reason=reason or "invalid_time"))
            continue
        if _outside_event(interval, event_start, event_end):
            rejected.append(RejectedSession(hit=hit, reason="outside_event_dates"))
            continue
        if blocked_time_overlaps(interval, profile.blocked_times):
            rejected.append(RejectedSession(hit=hit, reason="blocked_time_conflict"))
            continue
        fixed_conflicts = [
            item.id
            for item in fixed_items
            if intervals_overlap(interval, item.interval)
        ]
        if fixed_conflicts:
            rejected.append(
                RejectedSession(
                    hit=hit,
                    reason="fixed_session_conflict",
                    conflicting_with=sorted(fixed_conflicts),
                )
            )
            continue
        eligible.append(_Candidate(hit=hit, interval=interval))

    by_day: dict[date, list[_Candidate]] = defaultdict(list)
    for item in [*fixed_items, *eligible]:
        by_day[item.interval.day].append(item)

    selected: list[_Candidate] = []
    day_plans: list[_Plan] = []
    for day in sorted(by_day):
        day_selected, plan = _optimize_day(
            by_day[day], profile, _effective_day_limit(profile, day, daily_limits)
        )
        selected.extend(day_selected)
        day_plans.append(plan)
    selected.sort(key=lambda item: (item.interval.start, item.id))
    selected_ids = {item.id for item in selected}

    day_counts: dict[str, int] = defaultdict(int)
    for item in selected:
        day_counts[item.interval.day.isoformat()] += 1

    for item in eligible:
        if item.id in selected_ids:
            continue
        conflicts = sorted(
            other.id
            for other in selected
            if intervals_overlap(item.interval, other.interval)
        )
        if conflicts:
            reason = "time_conflict"
        elif (
            limit := _effective_day_limit(profile, item.interval.day, daily_limits)
        ) is not None and day_counts[item.interval.day.isoformat()] >= limit:
            reason = "daily_limit"
        else:
            reason = "lower_total_utility"
        rejected.append(
            RejectedSession(hit=item.hit, reason=reason, conflicting_with=conflicts)
        )
    rejected.sort(key=lambda item: (-item.hit.score, item.hit.session.id))

    intervals_by_id = {item.id: item.interval for item in eligible}
    alternatives = _alternatives(selected, rejected, intervals_by_id)
    transitions = sum(plan.transitions for plan in day_plans)
    relevance_total = sum(plan.relevance_total for plan in day_plans)
    venue_penalty = (
        transitions * VENUE_TRANSITION_PENALTY if profile.minimize_venue_changes else 0
    )
    conflict_count = sum(
        item.reason in {"time_conflict", "fixed_session_conflict"} for item in rejected
    )
    warnings = _warnings(day_counts, profile, conflict_count, daily_limits)
    return OptimizedSchedule(
        selected_sessions=[
            ScheduledSession(
                hit=item.hit,
                fixed=item.fixed,
                selection_reason=(
                    "fixed_session" if item.fixed else "selected_by_global_utility"
                ),
                event_local_start_at=item.interval.start,
                event_local_end_at=item.interval.end,
            )
            for item in selected
        ],
        rejected_sessions=rejected,
        alternatives=alternatives,
        score=float(relevance_total - venue_penalty),
        relevance_total=relevance_total,
        venue_penalty=venue_penalty,
        venue_transitions=transitions,
        sessions_per_day=dict(sorted(day_counts.items())),
        rejected_conflict_count=conflict_count,
        constraints=AppliedConstraints(
            blocked_time_count=len(profile.blocked_times),
            max_sessions_per_day=profile.max_sessions_per_day,
            fixed_session_count=len(fixed),
            minimize_venue_changes=profile.minimize_venue_changes,
            event_start=event_start,
            event_end=event_end,
            daily_limits={
                day.isoformat(): limit for day, limit in sorted(daily_limits.items())
            },
        ),
        warnings=warnings,
        candidate_count=len(best_hits),
    )


def _time_mode(
    hits: list[SearchHit], fixed: list[Session]
) -> tuple[bool, tzinfo | None]:
    """Fixed sessions set the mode; otherwise prefer aware candidate times."""
    timed_fixed = [session for session in fixed if session.start_at is not None]
    if timed_fixed:
        anchor = sorted(timed_fixed, key=lambda session: session.id)[0].start_at
        assert anchor is not None
        aware = is_aware(anchor)
        return aware, anchor.tzinfo if aware else None
    aware_candidates = sorted(
        (
            hit.session
            for hit in hits
            if hit.session.start_at is not None
            and hit.session.end_at is not None
            and is_aware(hit.session.start_at)
            and is_aware(hit.session.end_at)
            and hit.session.end_at > hit.session.start_at
            and hit.session.start_at.date() == hit.session.end_at.date()
        ),
        key=lambda session: session.id,
    )
    if aware_candidates:
        anchor = aware_candidates[0].start_at
        assert anchor is not None
        return True, anchor.tzinfo
    return False, None


def _unique_hits(hits: list[SearchHit]) -> dict[str, SearchHit]:
    unique: dict[str, SearchHit] = {}
    for hit in sorted(
        hits,
        key=lambda item: (-item.score, item.session.id, item.session.title.casefold()),
    ):
        unique.setdefault(hit.session.id, hit)
    return unique


def _prepare_fixed(
    fixed: list[Session],
    hits: dict[str, SearchHit],
    profile: AttendeeProfile,
    expect_aware: bool,
    event_timezone: tzinfo | None,
    event_start: date | None,
    event_end: date | None,
) -> list[_Candidate]:
    items: list[_Candidate] = []
    for session in fixed:
        interval, reason = session_interval(
            session, expect_aware=expect_aware, event_timezone=event_timezone
        )
        if reason or interval is None:
            raise ScheduleConstraintError(
                f"fixed session {session.id} has {reason or 'invalid_time'}"
            )
        if _outside_event(interval, event_start, event_end):
            raise ScheduleConstraintError(
                f"fixed session {session.id} is outside event dates"
            )
        if blocked_time_overlaps(interval, profile.blocked_times):
            raise ScheduleConstraintError(
                f"fixed session {session.id} overlaps a blocked time"
            )
        items.append(
            _Candidate(
                hit=(
                    hits[session.id].model_copy(update={"session": session})
                    if session.id in hits
                    else SearchHit(session=session, score=0)
                ),
                interval=interval,
                fixed=True,
            )
        )
    return items


def _validate_fixed(
    items: list[_Candidate], profile: AttendeeProfile, daily_limits: dict[date, int]
) -> None:
    ordered = sorted(items, key=lambda item: (item.interval.start, item.id))
    counts: dict[date, int] = defaultdict(int)
    for index, item in enumerate(ordered):
        counts[item.interval.day] += 1
        limit = _effective_day_limit(profile, item.interval.day, daily_limits)
        if limit and counts[item.interval.day] > limit:
            raise ScheduleConstraintError("fixed sessions exceed max_sessions_per_day")
        if index and intervals_overlap(ordered[index - 1].interval, item.interval):
            raise ScheduleConstraintError("fixed sessions overlap")


def _outside_event(
    interval: SessionInterval, event_start: date | None, event_end: date | None
) -> bool:
    return bool(
        (event_start and interval.day < event_start)
        or (event_end and interval.day > event_end)
    )


def _optimize_day(
    items: list[_Candidate], profile: AttendeeProfile, day_limit: int | None = None
) -> tuple[list[_Candidate], _Plan]:
    nodes = sorted(
        items, key=lambda item: (item.interval.end, item.interval.start, item.id)
    )
    limit = day_limit or profile.max_sessions_per_day or len(nodes)
    fixed_prefix = [0]
    for node in nodes:
        fixed_prefix.append(fixed_prefix[-1] + int(node.fixed))

    empty = _Plan()
    states: list[dict[tuple[int, str | None], _Plan]] = [{} for _ in nodes]
    for current_index, current in enumerate(nodes):
        for previous_index in range(-1, current_index):
            if fixed_prefix[current_index] > fixed_prefix[previous_index + 1]:
                continue  # A required fixed session would be skipped.
            if previous_index >= 0 and (
                nodes[previous_index].interval.end > current.interval.start
            ):
                continue
            prior_states = (
                [empty] if previous_index < 0 else states[previous_index].values()
            )
            for prior in prior_states:
                if len(prior.indices) >= limit:
                    continue
                transition = int(
                    prior.last_known_venue is not None
                    and current.venue is not None
                    and prior.last_known_venue != current.venue
                )
                next_plan = _Plan(
                    score=(
                        prior.score
                        + current.hit.score
                        - (
                            transition * VENUE_TRANSITION_PENALTY
                            if profile.minimize_venue_changes
                            else 0
                        )
                    ),
                    relevance_total=prior.relevance_total + current.hit.score,
                    transitions=prior.transitions + transition,
                    indices=(*prior.indices, current_index),
                    ids=(*prior.ids, current.id),
                    last_known_venue=current.venue or prior.last_known_venue,
                )
                key = (len(next_plan.indices), next_plan.last_known_venue)
                old = states[current_index].get(key)
                if old is None or _better(next_plan, old):
                    states[current_index][key] = next_plan

    best = empty if fixed_prefix[-1] == 0 else None
    for index, state in enumerate(states):
        if fixed_prefix[-1] > fixed_prefix[index + 1]:
            continue  # A required fixed session remains after this path.
        for plan in state.values():
            if best is None or _better(plan, best):
                best = plan
    if best is None:
        raise ScheduleConstraintError("fixed sessions cannot be scheduled")
    return [nodes[index] for index in best.indices], best


def _effective_day_limit(
    profile: AttendeeProfile, day: date, daily_limits: dict[date, int]
) -> int | None:
    override = daily_limits.get(day)
    global_limit = profile.max_sessions_per_day
    if override is None:
        return global_limit
    if global_limit is None:
        return override
    return min(override, global_limit)


def _better(candidate: _Plan, current: _Plan) -> bool:
    if candidate.score != current.score:
        return candidate.score > current.score
    if len(candidate.indices) != len(current.indices):
        return len(candidate.indices) < len(current.indices)
    return candidate.ids < current.ids


def _alternatives(
    selected: list[_Candidate],
    rejected: list[RejectedSession],
    intervals_by_id: dict[str, SessionInterval],
) -> dict[str, list[ScheduleAlternative]]:
    result: dict[str, list[ScheduleAlternative]] = {}
    for chosen in selected:
        if chosen.fixed:
            continue
        options: list[ScheduleAlternative] = []
        for item in rejected:
            interval = intervals_by_id.get(item.hit.session.id)
            if (
                item.reason != "time_conflict"
                or item.hit.score <= 0
                or interval is None
                or not intervals_overlap(interval, chosen.interval)
            ):
                continue
            if any(
                other.id != chosen.id and intervals_overlap(interval, other.interval)
                for other in selected
            ):
                continue
            options.append(
                ScheduleAlternative(
                    hit=item.hit,
                    rejected_reason=item.reason,
                    replaces_session_id=chosen.id,
                )
            )
            if len(options) >= MAX_ALTERNATIVES_PER_SESSION:
                break
        if options:
            result[chosen.id] = options
    return result


def _warnings(
    day_counts: dict[str, int],
    profile: AttendeeProfile,
    conflict_count: int,
    daily_limits: dict[date, int],
) -> list[str]:
    warnings = []
    for day, count in sorted(day_counts.items()):
        limit = _effective_day_limit(profile, date.fromisoformat(day), daily_limits)
        if limit is not None and count == limit:
            weekday = WEEKDAY_NAMES[date.fromisoformat(day).weekday()]
            warnings.append(
                f"{weekday} reached the configured maximum of {count} sessions."
            )
    if conflict_count:
        warnings.append(
            f"{conflict_count} candidate sessions were excluded by time conflicts."
        )
    return warnings
