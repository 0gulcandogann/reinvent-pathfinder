"""Parse the published AWS bulk reservation response, without raw AWS JSON leaks."""

from app.mutations.models import OperationFailure, ReservationResult

RESERVATION_BATCH_SIZE = 10
SAFE_FAILURE_MESSAGES = {
    "sessionNotReservable": "Session is not reservable.",
    "scheduleConflict": "Session conflicts with the attendee schedule.",
    "alreadyScheduled": "Session is already reserved.",
    "sessionFull": "Session is full.",
    "insufficientAccess": "Attendee access is insufficient.",
    "timePassed": "Reservation time has passed.",
    "other": "Reservation was refused.",
}


class ReservationResponseError(ValueError):
    """A bulk response cannot be reconciled with the submitted IDs."""


def normalize_reservation_result(
    payload: object, requested: list[str]
) -> ReservationResult:
    if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
        raise ReservationResponseError("reservation response has no result object")
    result = payload["result"]
    successful = result.get("successful")
    failed = result.get("failed")
    if not isinstance(successful, list) or not isinstance(failed, list):
        raise ReservationResponseError("reservation result arrays are missing")
    if any(not isinstance(value, str) or not value for value in successful):
        raise ReservationResponseError("reservation success contains an invalid ID")
    failures: list[OperationFailure] = []
    for value in failed:
        if not isinstance(value, dict):
            raise ReservationResponseError("reservation failure is malformed")
        session_id = value.get("sessionId")
        code = value.get("code")
        if (
            not isinstance(session_id, str)
            or not session_id
            or not isinstance(code, str)
        ):
            raise ReservationResponseError("reservation failure lacks ID or code")
        conflicts = value.get("conflictsWith", [])
        if not isinstance(conflicts, list) or any(
            not isinstance(item, str) or not item for item in conflicts
        ):
            raise ReservationResponseError("reservation conflict IDs are malformed")
        failures.append(
            OperationFailure(
                session_id=session_id,
                code=code,
                message=SAFE_FAILURE_MESSAGES.get(code, "Reservation was refused."),
                conflicts_with=conflicts,
            )
        )
    reported = [*successful, *(failure.session_id for failure in failures)]
    if len(reported) != len(set(reported)) or set(reported) != set(requested):
        raise ReservationResponseError(
            "reservation result does not match requested IDs"
        )
    return ReservationResult(succeeded=successful, failed=failures)
