"""Confirmed writes followed by GetSchedule source-of-truth verification."""

from app.clients.events import EventsClient
from app.clients.events_api import EventsApiError
from app.mutations.models import (
    CancellationResult,
    MutationAction,
    MutationExecutionResult,
    OperationFailure,
    ReservationResult,
    ScheduleMutationPlan,
    VerificationFailure,
)
from app.mutations.normalize import RESERVATION_BATCH_SIZE
from app.schedule.models import AttendeeSchedule
from app.schedule.normalize import normalize_schedule


class MutationExecutionError(ValueError):
    """A plan or live-write configuration failed before any mutation."""


class MutationExecutor:
    def __init__(self, client: EventsClient | None) -> None:
        self.client = client

    async def execute(
        self, plan: ScheduleMutationPlan, *, confirmed: bool = False
    ) -> MutationExecutionResult:
        if not confirmed:
            return MutationExecutionResult(status="confirmation_required")
        _validate_plan(plan)
        if self.client is None:
            raise MutationExecutionError("AWS Events schedule writes are disabled")
        if getattr(self.client, "enable_writes", True) is False:
            raise MutationExecutionError("AWS Events schedule writes are disabled")

        initial = await self._read_schedule()
        if initial is None:
            return _read_failure()
        if initial != plan.baseline_schedule:
            return MutationExecutionResult(
                status="stale_plan",
                verified_schedule=initial,
                verification_failures=[
                    VerificationFailure(
                        kind="stale_plan",
                        message=(
                            "Attendee schedule changed after planning; "
                            "replan before writing."
                        ),
                    )
                ],
            )

        replacements = {
            item.old_session_id: item.new_session_id for item in plan.replacements
        }
        deferred_new = {
            item.session_id for item in plan.additions if item.conflicts_with
        }
        deferred_old = {old for old, new in replacements.items() if new in deferred_new}
        skipped = [
            item
            for item in [*plan.additions, *plan.removals]
            if item.session_id in deferred_new | deferred_old
        ]
        failures = [
            VerificationFailure(
                kind="replacement_deferred",
                session_id=old,
                message=(
                    f"Replacement {old} → {replacements[old]} overlaps; "
                    "no safe automatic write order exists."
                ),
            )
            for old in sorted(deferred_old)
        ]

        reservation = ReservationResult()
        addition_ids = [
            item.session_id
            for item in plan.additions
            if item.session_id not in deferred_new
        ]
        for offset in range(0, len(addition_ids), RESERVATION_BATCH_SIZE):
            batch = addition_ids[offset : offset + RESERVATION_BATCH_SIZE]
            try:
                outcome = await self.client.reserve_sessions(batch)
            except Exception:
                reservation.failed.extend(
                    OperationFailure(
                        session_id=session_id,
                        code="operationUncertain",
                        message=(
                            "Reservation response unavailable; "
                            "final state must be checked."
                        ),
                    )
                    for session_id in batch
                )
                # A write may have succeeded despite a lost response. Stop sending
                # further batches and rely on GetSchedule before any cancellation.
                skipped.extend(
                    item
                    for item in plan.additions
                    if item.session_id in addition_ids[offset + len(batch) :]
                )
                break
            reservation.succeeded.extend(outcome.succeeded)
            reservation.failed.extend(outcome.failed)

        after_reservations = await self._read_schedule() if addition_ids else initial
        if after_reservations is None:
            return _read_failure(reservation=reservation, skipped=skipped)
        reserved_after_add = set(after_reservations.reserved_session_ids)
        cancellation = CancellationResult()
        for item in plan.removals:
            if item.session_id in deferred_old:
                continue
            replacement_new = replacements.get(item.session_id)
            if replacement_new and (
                replacement_new not in reservation.succeeded
                or replacement_new not in reserved_after_add
            ):
                skipped.append(item)
                failures.append(
                    VerificationFailure(
                        kind="replacement_deferred",
                        session_id=item.session_id,
                        message="Old reservation kept: replacement was not verified.",
                    )
                )
                continue
            try:
                await self.client.cancel_reservation(item.session_id)
            except EventsApiError as error:
                cancellation.failed.append(
                    OperationFailure(
                        session_id=item.session_id,
                        code=f"http_{error.status_code or 'unknown'}",
                        message="Cancellation was refused or its outcome is uncertain.",
                    )
                )
            except Exception:
                cancellation.failed.append(
                    OperationFailure(
                        session_id=item.session_id,
                        code="operationUncertain",
                        message="Cancellation outcome is uncertain.",
                    )
                )
            else:
                cancellation.succeeded.append(item.session_id)

        final = (
            await self._read_schedule()
            if cancellation.succeeded or cancellation.failed
            else after_reservations
        )
        if final is None:
            return _read_failure(
                reservation=reservation, cancellation=cancellation, skipped=skipped
            )
        final_ids = set(final.reserved_session_ids)
        for session_id in reservation.succeeded:
            if session_id not in final_ids:
                failures.append(
                    VerificationFailure(
                        kind="reported_success_missing",
                        session_id=session_id,
                        message=(
                            "Reservation was reported successful but is "
                            "absent from GetSchedule."
                        ),
                    )
                )
        for session_id in cancellation.succeeded:
            if session_id in final_ids:
                failures.append(
                    VerificationFailure(
                        kind="cancellation_still_present",
                        session_id=session_id,
                        message=(
                            "Cancellation was reported successful but "
                            "remains in GetSchedule."
                        ),
                    )
                )
        for item in plan.unchanged:
            if item.session_id not in final_ids:
                failures.append(
                    VerificationFailure(
                        kind="unchanged_missing",
                        session_id=item.session_id,
                        message="Existing reservation is missing from GetSchedule.",
                    )
                )
        for item in [*reservation.failed, *cancellation.failed]:
            failures.append(
                VerificationFailure(
                    kind="api_operation_failed",
                    session_id=item.session_id,
                    message=item.message,
                )
            )
        mismatch = any(
            item.kind
            in {
                "reported_success_missing",
                "cancellation_still_present",
                "unchanged_missing",
            }
            for item in failures
        )
        status = (
            "verification_failed"
            if mismatch
            else "partially_completed"
            if failures or skipped
            else "completed"
        )
        return MutationExecutionResult(
            status=status,
            reservation_result=reservation,
            cancellation_result=cancellation,
            verified_schedule=final,
            verification_failures=failures,
            skipped_actions=skipped,
        )

    async def _read_schedule(self) -> AttendeeSchedule | None:
        try:
            return normalize_schedule(await self.client.get_schedule())
        except Exception:
            return None


def _read_failure(
    *,
    reservation: ReservationResult | None = None,
    cancellation: CancellationResult | None = None,
    skipped: list[MutationAction] | None = None,
) -> MutationExecutionResult:
    return MutationExecutionResult(
        status="verification_failed",
        reservation_result=reservation or ReservationResult(),
        cancellation_result=cancellation or CancellationResult(),
        skipped_actions=skipped or [],
        verification_failures=[
            VerificationFailure(
                kind="get_schedule_failed",
                message="GetSchedule could not verify the attendee schedule.",
            )
        ],
    )


def _validate_plan(plan: ScheduleMutationPlan) -> None:
    baseline = set(plan.baseline_schedule.reserved_session_ids)
    additions = [item.session_id for item in plan.additions]
    removals = [item.session_id for item in plan.removals]
    unchanged = [item.session_id for item in plan.unchanged]
    if any(len(group) != len(set(group)) for group in (additions, removals, unchanged)):
        raise MutationExecutionError("plan contains duplicate actions")
    if set(removals) | set(unchanged) != baseline or set(removals) & set(unchanged):
        raise MutationExecutionError("plan does not account for baseline reservations")
    if set(additions) & baseline:
        raise MutationExecutionError("plan tries to reserve an existing session")
    if (
        any(item.action != "reserve" for item in plan.additions)
        or any(item.action != "cancel" for item in plan.removals)
        or any(item.action != "keep" for item in plan.unchanged)
    ):
        raise MutationExecutionError("plan contains mismatched action types")
    if any(
        item.old_session_id not in removals or item.new_session_id not in additions
        for item in plan.replacements
    ):
        raise MutationExecutionError("plan contains an invalid replacement")
    old_ids = [item.old_session_id for item in plan.replacements]
    new_ids = [item.new_session_id for item in plan.replacements]
    if len(old_ids) != len(set(old_ids)) or len(new_ids) != len(set(new_ids)):
        raise MutationExecutionError("plan contains duplicate replacements")
