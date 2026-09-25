"""Side-effect-free diff from current reservations to an optimized itinerary."""

from collections.abc import Iterable

from app.catalog.repository import SessionRepository
from app.models.session import Session
from app.mutations.models import MutationAction, Replacement, ScheduleMutationPlan
from app.optimizer.models import OptimizedSchedule
from app.optimizer.time import intervals_overlap, is_aware, session_interval
from app.schedule.models import AttendeeSchedule


class MutationPlanError(ValueError):
    """The requested changes cannot be represented safely."""


class MutationPlanner:
    def __init__(self, repository: SessionRepository) -> None:
        self.repository = repository

    def build(
        self,
        current: AttendeeSchedule,
        optimized: OptimizedSchedule,
        *,
        remove_session_ids: Iterable[str] = (),
        replacements: Iterable[Replacement] = (),
    ) -> ScheduleMutationPlan:
        selected = [item.hit.session for item in optimized.selected_sessions]
        selected_by_id = {item.id: item for item in selected}
        if len(selected_by_id) != len(selected):
            raise MutationPlanError("optimized schedule contains duplicate session IDs")
        replacement_list = sorted(
            replacements, key=lambda item: (item.old_session_id, item.new_session_id)
        )
        old_ids = [item.old_session_id for item in replacement_list]
        new_ids = [item.new_session_id for item in replacement_list]
        if len(set(old_ids)) != len(old_ids) or len(set(new_ids)) != len(new_ids):
            raise MutationPlanError("replacement session IDs must be unique")
        baseline_ids = set(current.reserved_session_ids)
        removals = set(remove_session_ids) | set(old_ids)
        if not removals <= baseline_ids:
            raise MutationPlanError("only existing reservations may be cancelled")
        if removals & selected_by_id.keys():
            raise MutationPlanError("a removed session cannot remain selected")
        unchanged_ids = baseline_ids - removals
        if not unchanged_ids <= selected_by_id.keys():
            raise MutationPlanError(
                "existing reservations must remain selected or be explicitly removed"
            )
        addition_ids = selected_by_id.keys() - baseline_ids
        if not set(new_ids) <= addition_ids:
            raise MutationPlanError("replacement target must be a new selected session")
        _validate_itinerary(selected, current)

        warnings: list[str] = []
        conflicts_by_new: dict[str, list[str]] = {}
        for relationship in replacement_list:
            old = self.repository.get(relationship.old_session_id)
            new = selected_by_id[relationship.new_session_id]
            if old is None:
                raise MutationPlanError(
                    "replacement source is missing from the local catalog"
                )
            if _sessions_overlap(old, new):
                conflicts_by_new.setdefault(new.id, []).append(old.id)
                warnings.append(
                    f"Replacement {old.id} → {new.id} overlaps; automatic "
                    "execution will defer this pair."
                )
        paired = {
            (item.old_session_id, item.new_session_id) for item in replacement_list
        }
        for old_id in sorted(removals):
            old = self.repository.get(old_id)
            if old is None:
                raise MutationPlanError(
                    "removed session is missing from the local catalog"
                )
            for new_id in sorted(addition_ids):
                if (
                    _sessions_overlap(old, selected_by_id[new_id])
                    and (
                        old_id,
                        new_id,
                    )
                    not in paired
                ):
                    raise MutationPlanError(
                        "an overlapping addition and removal need an "
                        "explicit replacement"
                    )

        return ScheduleMutationPlan(
            baseline_schedule=current.model_copy(deep=True),
            additions=[
                MutationAction(
                    session_id=session_id,
                    title=selected_by_id[session_id].title,
                    action="reserve",
                    reason="selected_by_pathfinder",
                    provenance="pathfinder_selected",
                    conflicts_with=conflicts_by_new.get(session_id, []),
                )
                for session_id in sorted(addition_ids)
            ],
            removals=[
                MutationAction(
                    session_id=session_id,
                    title=(
                        session.title
                        if (session := self.repository.get(session_id))
                        else None
                    ),
                    action="cancel",
                    reason=(
                        "explicit_replacement"
                        if session_id in old_ids
                        else "explicit_removal"
                    ),
                    provenance="existing_reserved",
                )
                for session_id in sorted(removals)
            ],
            unchanged=[
                MutationAction(
                    session_id=session_id,
                    title=selected_by_id[session_id].title,
                    action="keep",
                    reason="already_reserved",
                    provenance="existing_reserved",
                )
                for session_id in sorted(unchanged_ids)
            ],
            replacements=sorted(
                replacement_list,
                key=lambda item: (item.old_session_id, item.new_session_id),
            ),
            warnings=warnings,
        )


def _validate_itinerary(sessions: list[Session], current: AttendeeSchedule) -> None:
    if not sessions:
        return
    aware = is_aware(sessions[0].start_at) if sessions[0].start_at else False
    zone = sessions[0].start_at.tzinfo if aware else None
    intervals = []
    for session in sessions:
        interval, reason = session_interval(
            session, expect_aware=aware, event_timezone=zone
        )
        if reason or interval is None:
            raise MutationPlanError(
                f"selected session {session.id} has {reason or 'invalid_time'}"
            )
        if current.personal_time:
            if not aware:
                raise MutationPlanError(
                    "selected sessions need timezone-aware times with personal time"
                )
            if any(
                interval.start < block.end_at and block.start_at < interval.end
                for block in current.personal_time
            ):
                raise MutationPlanError(
                    f"selected session {session.id} overlaps personal time"
                )
        for earlier in intervals:
            if intervals_overlap(interval, earlier):
                raise MutationPlanError(
                    "optimized schedule contains overlapping sessions"
                )
        intervals.append(interval)


def _sessions_overlap(first: Session, second: Session) -> bool:
    aware = is_aware(first.start_at) if first.start_at else False
    zone = first.start_at.tzinfo if aware else None
    first_interval, first_reason = session_interval(
        first, expect_aware=aware, event_timezone=zone
    )
    second_interval, second_reason = session_interval(
        second, expect_aware=aware, event_timezone=zone
    )
    if first_reason or first_interval is None:
        raise MutationPlanError("replacement source has invalid time")
    if second_reason or second_interval is None:
        raise MutationPlanError("replacement target has invalid time or timezone")
    return intervals_overlap(first_interval, second_interval)
