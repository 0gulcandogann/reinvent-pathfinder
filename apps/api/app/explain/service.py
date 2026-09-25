"""Build factual explanations from M3 hits and M4 optimizer output."""

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, time
from math import ceil

from app.explain.models import (
    BlockedTimeUsage,
    DisplacedCandidate,
    GoalCoverage,
    RejectedExplanation,
    ScheduleExplanation,
    ScheduleFit,
    ScheduleInsight,
    ScheduleMetrics,
    SessionExplanation,
    VenueEffect,
)
from app.models.profile import WEEKDAY_NAMES, AttendeeProfile
from app.optimizer.models import OptimizedSchedule, RejectedSession, ScheduledSession
from app.optimizer.solve import VENUE_TRANSITION_PENALTY
from app.ranking.session_search import SearchHit

HIGH_SCORING_CONFLICT_RATIO = 0.75
MAX_DISPLACED_CANDIDATES = 3


def explain_schedule(
    schedule: OptimizedSchedule,
    profile: AttendeeProfile,
    *,
    capped_candidates: Iterable[SearchHit] = (),
    candidate_total: int | None = None,
    candidate_limit: int | None = None,
) -> ScheduleExplanation:
    """Explain the given schedule without changing it or rescoring sessions."""
    considered_hits = [
        *(item.hit for item in schedule.selected_sessions),
        *(item.hit for item in schedule.rejected_sessions),
    ]
    top_score = max((hit.score for hit in considered_hits), default=0)
    high_threshold = (
        max(1, ceil(top_score * HIGH_SCORING_CONFLICT_RATIO)) if top_score > 0 else None
    )
    rejected = [
        _rejection(item, profile, high_threshold) for item in schedule.rejected_sessions
    ]
    known_ids = {hit.session.id for hit in considered_hits}
    for hit in capped_candidates:
        if hit.session.id in known_ids:
            continue
        known_ids.add(hit.session.id)
        rejected.append(
            RejectedExplanation(
                session_id=hit.session.id,
                code=hit.session.code,
                title=hit.session.title,
                relevance_score=hit.score,
                reason="candidate_cap",
                important=high_threshold is not None and hit.score >= high_threshold,
                message=(
                    f"Outside the top {candidate_limit} M3-ranked candidates; "
                    "the optimizer did not evaluate it."
                ),
            )
        )
    rejected.sort(key=lambda item: (-item.relevance_score, item.session_id))

    ordered_days = _sessions_by_day(schedule)
    venue_effects, transitions_by_day = _venue_effects(ordered_days, profile)
    fits = _schedule_fits(ordered_days)
    selected_explanations = [
        _selected_explanation(item, schedule, venue_effects[item.hit.session.id], fits)
        for item in schedule.selected_sessions
    ]

    high_conflicts = sum(
        item.reason in {"time_conflict", "fixed_session_conflict"}
        and high_threshold is not None
        and item.hit.score >= high_threshold
        for item in schedule.rejected_sessions
    )
    daily_limit = profile.max_sessions_per_day
    days_at_limit = [
        day
        for day, count in sorted(schedule.sessions_per_day.items())
        if daily_limit is not None and count == daily_limit
    ]
    blocked_usage = BlockedTimeUsage(
        configured_blocks=len(profile.blocked_times),
        configured_minutes=sum(
            _block_minutes(block.start, block.end) for block in profile.blocked_times
        ),
        excluded_candidate_count=sum(
            item.reason == "blocked_time_conflict"
            for item in schedule.rejected_sessions
        ),
    )
    cap_excluded_count = (
        max(0, candidate_total - candidate_limit)
        if candidate_total is not None and candidate_limit is not None
        else 0
    )
    metrics = ScheduleMetrics(
        selected_session_count=len(schedule.selected_sessions),
        sessions_per_day=dict(schedule.sessions_per_day),
        venue_transitions_per_day=transitions_by_day,
        total_venue_transitions=schedule.venue_transitions,
        rejected_high_scoring_conflicts=high_conflicts,
        high_score_threshold=high_threshold,
        days_at_daily_limit=days_at_limit,
        blocked_time_usage=blocked_usage,
        fixed_session_count=schedule.constraints.fixed_session_count,
        total_selected_utility=schedule.score,
        candidate_count=schedule.candidate_count,
        candidate_cap_excluded_count=cap_excluded_count,
    )
    return ScheduleExplanation(
        sessions=selected_explanations,
        rejected=rejected,
        insights=_insights(metrics, len(rejected) - len(schedule.rejected_sessions)),
        goal_coverage=_goal_coverage(schedule, profile),
        metrics=metrics,
    )


def _selected_explanation(
    item: ScheduledSession,
    schedule: OptimizedSchedule,
    venue_effect: VenueEffect,
    fits: dict[str, ScheduleFit],
) -> SessionExplanation:
    hit = item.hit
    matches = hit.matched_preferences
    displaced = [
        DisplacedCandidate(
            session_id=rejected.hit.session.id,
            title=rejected.hit.session.title,
            relevance_score=rejected.hit.score,
            rejection_reason=rejected.reason,
        )
        for rejected in schedule.rejected_sessions
        if rejected.reason in {"time_conflict", "fixed_session_conflict"}
        and hit.session.id in rejected.conflicting_with
    ][:MAX_DISPLACED_CANDIDATES]
    return SessionExplanation(
        session_id=hit.session.id,
        code=hit.session.code,
        title=hit.session.title,
        final_relevance_score=hit.score,
        text_relevance_score=hit.text_score,
        preference_score=hit.preference_score,
        matched_terms=list(hit.matched_terms),
        field_scores=dict(hit.field_scores),
        matched_interests=list(matches.get("interests", [])),
        matched_preferred_services=list(matches.get("preferred_services", [])),
        matched_preferred_topics=list(matches.get("preferred_topics", [])),
        matched_desired_levels=list(matches.get("desired_levels", [])),
        matched_learning_goals=list(matches.get("learning_goals", [])),
        depth_bonus=hit.preference_contributions.get("prioritize_depth", 0),
        preference_contributions=dict(hit.preference_contributions),
        penalties=dict(hit.penalties),
        venue_effect=venue_effect,
        schedule_fit=fits[hit.session.id],
        displaced_candidates=displaced,
    )


def _rejection(
    item: RejectedSession,
    profile: AttendeeProfile,
    high_threshold: int | None,
) -> RejectedExplanation:
    reason = (
        "lower_total_schedule_utility"
        if item.reason == "lower_total_utility"
        else item.reason
    )
    conflicts = list(item.conflicting_with)
    if reason == "time_conflict":
        message = (
            f"Conflicts with selected session(s) {', '.join(conflicts)}; "
            "the complete selected schedule was preferred by the optimizer."
        )
    elif reason == "fixed_session_conflict":
        message = f"Conflicts with fixed session(s) {', '.join(conflicts)}."
    elif reason == "blocked_time_conflict":
        message = "Overlaps an explicit blocked time."
    elif reason == "daily_limit":
        message = (
            "Its day reached the configured maximum of "
            f"{profile.max_sessions_per_day} sessions."
        )
    elif reason == "lower_total_schedule_utility":
        message = (
            "A different combination was preferred by total schedule utility "
            "and deterministic tie-break rules."
        )
    elif reason == "invalid_time":
        message = "Missing or invalid session times prevented scheduling."
    elif reason == "timezone_mismatch":
        message = "Its time awareness differs from the event schedule."
    elif reason == "cross_day_session":
        message = "Cross-day sessions are unsupported in this optimizer version."
    elif reason == "outside_event_dates":
        message = "Outside the configured event date range."
    else:
        message = f"Excluded by optimizer constraint: {reason}."
    return RejectedExplanation(
        session_id=item.hit.session.id,
        code=item.hit.session.code,
        title=item.hit.session.title,
        relevance_score=item.hit.score,
        reason=reason,
        conflicting_session_ids=conflicts,
        important=high_threshold is not None and item.hit.score >= high_threshold,
        message=message,
    )


def _sessions_by_day(
    schedule: OptimizedSchedule,
) -> dict[str, list[ScheduledSession]]:
    by_day: dict[str, list[ScheduledSession]] = defaultdict(list)
    for item in schedule.selected_sessions:
        start = item.event_local_start_at or item.hit.session.start_at
        if start is not None:
            by_day[start.date().isoformat()].append(item)
    for items in by_day.values():
        items.sort(
            key=lambda item: (
                item.event_local_start_at or item.hit.session.start_at,
                item.hit.session.id,
            )
        )
    return dict(sorted(by_day.items()))


def _venue_effects(
    by_day: dict[str, list[ScheduledSession]], profile: AttendeeProfile
) -> tuple[dict[str, VenueEffect], dict[str, int]]:
    effects: dict[str, VenueEffect] = {}
    transitions: dict[str, int] = {}
    for day, items in by_day.items():
        previous_venue: str | None = None
        count = 0
        for item in items:
            venue = item.hit.session.venue or None
            normalized = venue.strip().casefold() if venue and venue.strip() else None
            changed = bool(
                previous_venue is not None
                and normalized is not None
                and previous_venue.casefold() != normalized
            )
            count += int(changed)
            penalty = (
                VENUE_TRANSITION_PENALTY
                if changed and profile.minimize_venue_changes
                else 0
            )
            if normalized is None:
                message = "Venue unknown; no transition penalty was applied."
            elif previous_venue is None:
                message = "First known venue today; no transition penalty."
            elif changed and profile.minimize_venue_changes:
                message = (
                    f"Changes venue from {previous_venue} to {venue}; "
                    f"{penalty}-point penalty."
                )
            elif changed:
                message = (
                    f"Changes venue from {previous_venue} to {venue}; "
                    "venue minimization is off."
                )
            else:
                message = "Same known venue as before; no transition penalty."
            effects[item.hit.session.id] = VenueEffect(
                venue=venue,
                previous_known_venue=previous_venue,
                transition_from_previous=changed,
                penalty_points=penalty,
                message=message,
            )
            if normalized is not None:
                previous_venue = venue
        transitions[day] = count
    return effects, transitions


def _schedule_fits(
    by_day: dict[str, list[ScheduledSession]],
) -> dict[str, ScheduleFit]:
    fits: dict[str, ScheduleFit] = {}
    for items in by_day.values():
        for index, item in enumerate(items):
            previous_id = items[index - 1].hit.session.id if index else None
            next_id = (
                items[index + 1].hit.session.id if index + 1 < len(items) else None
            )
            if item.fixed:
                message = "Preserved as a fixed session before optimization."
            elif previous_id and next_id:
                message = (
                    f"Fits between {previous_id} and {next_id} without a time conflict."
                )
            elif previous_id:
                message = f"Fits after {previous_id} without a time conflict."
            elif next_id:
                message = f"Fits before {next_id} without a time conflict."
            else:
                message = "Fits available time without a conflict."
            fits[item.hit.session.id] = ScheduleFit(
                fixed=item.fixed,
                previous_session_id=previous_id,
                next_session_id=next_id,
                message=message,
            )
    return fits


def _block_minutes(start: time, end: time) -> int:
    anchor = date(2000, 1, 1)
    return round(
        (
            datetime.combine(anchor, end) - datetime.combine(anchor, start)
        ).total_seconds()
        / 60
    )


def _insights(metrics: ScheduleMetrics, capped_shown: int) -> list[ScheduleInsight]:
    insights = [
        ScheduleInsight(
            code="selected_utility",
            message=(
                f"Selected {metrics.selected_session_count} sessions with "
                f"total utility {metrics.total_selected_utility:g}."
            ),
            count=metrics.selected_session_count,
        )
    ]
    for day in metrics.days_at_daily_limit:
        weekday = WEEKDAY_NAMES[date.fromisoformat(day).weekday()]
        count = metrics.sessions_per_day[day]
        insights.append(
            ScheduleInsight(
                code="daily_limit_reached",
                message=(
                    f"{weekday} reached your configured maximum of {count} sessions."
                ),
                day=date.fromisoformat(day),
                count=count,
            )
        )
    for day, count in metrics.venue_transitions_per_day.items():
        if count:
            weekday = WEEKDAY_NAMES[date.fromisoformat(day).weekday()]
            insights.append(
                ScheduleInsight(
                    code="venue_transitions",
                    message=f"{weekday} contains {count} venue transitions.",
                    day=date.fromisoformat(day),
                    count=count,
                )
            )
    if metrics.rejected_high_scoring_conflicts:
        count = metrics.rejected_high_scoring_conflicts
        insights.append(
            ScheduleInsight(
                code="high_scoring_conflicts",
                message=(
                    f"{count} highly ranked candidate sessions were excluded "
                    "by schedule conflicts."
                ),
                count=count,
            )
        )
    usage = metrics.blocked_time_usage
    if usage.configured_blocks:
        period_word = "period" if usage.configured_blocks == 1 else "periods"
        candidate_word = (
            "candidate session"
            if usage.excluded_candidate_count == 1
            else "candidate sessions"
        )
        insights.append(
            ScheduleInsight(
                code="blocked_time_usage",
                message=(
                    f"{usage.configured_blocks} blocked {period_word} excluded "
                    f"{usage.excluded_candidate_count} {candidate_word}."
                ),
                count=usage.excluded_candidate_count,
            )
        )
    if metrics.candidate_cap_excluded_count:
        count = metrics.candidate_cap_excluded_count
        insights.append(
            ScheduleInsight(
                code="candidate_cap",
                message=(
                    f"{count} ranked candidates were outside the optimizer pool; "
                    f"{capped_shown} are shown as examples."
                ),
                count=count,
            )
        )
    return insights


def _goal_coverage(
    schedule: OptimizedSchedule, profile: AttendeeProfile
) -> dict[str, GoalCoverage]:
    selected = {item.hit.session.id: item.hit for item in schedule.selected_sessions}
    considered = dict(selected)
    hard_exclusions = {
        "blocked_time_conflict",
        "fixed_session_conflict",
        "invalid_time",
        "timezone_mismatch",
        "cross_day_session",
        "outside_event_dates",
    }
    considered.update(
        (item.hit.session.id, item.hit)
        for item in schedule.rejected_sessions
        if item.reason not in hard_exclusions
    )
    opportunity_limit = max(1, len(selected))
    coverage: dict[str, GoalCoverage] = {}
    for kind, values, match_field in (
        ("interest", profile.interests, "interests"),
        ("learning_goal", profile.learning_goals, "learning_goals"),
    ):
        for value in values:
            key = f"{kind}:{value.casefold()}"
            if key in coverage:
                continue
            matching = [
                hit
                for hit in considered.values()
                if any(
                    match.casefold() == value.casefold()
                    for match in hit.matched_preferences.get(match_field, [])
                )
            ]
            available_scores = sorted(
                (max(0, hit.score) for hit in matching), reverse=True
            )
            available = sum(available_scores[:opportunity_limit])
            selected_ids = sorted(
                hit.session.id for hit in matching if hit.session.id in selected
            )
            selected_score = sum(
                max(0, selected[session_id].score) for session_id in selected_ids
            )
            percentage = (
                max(0, min(100, round(100 * selected_score / available)))
                if available
                else 0
            )
            status = (
                "no_opportunity"
                if not available
                else "covered"
                if selected_score
                else "uncovered"
            )
            coverage[key] = GoalCoverage(
                label=value,
                kind=kind,
                percentage=percentage,
                selected_opportunity_score=selected_score,
                available_opportunity_score=available,
                selected_session_ids=selected_ids,
                available_candidate_count=len(matching),
                status=status,
            )
    return coverage
