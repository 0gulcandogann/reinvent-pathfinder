from collections.abc import AsyncIterator, Iterable
from copy import deepcopy

from app.mutations.models import OperationFailure, ReservationResult
from app.mutations.normalize import RESERVATION_BATCH_SIZE, SAFE_FAILURE_MESSAGES


class FakeEventsClient:
    """In-memory AWS-shaped catalog and schedule source for offline tests."""

    def __init__(
        self,
        sessions: Iterable[object] = (),
        *,
        schedule: object | None = None,
        reservation_failures: dict[str, str] | None = None,
        cancellation_failures: dict[str, int] | None = None,
        stale_final_schedule: object | None = None,
        fail_get_schedule_on_calls: set[int] | None = None,
    ) -> None:
        self.sessions = list(sessions)
        self.schedule = (
            deepcopy(schedule)
            if schedule is not None
            else {"schedule": {"reserved": [], "favorites": [], "personalTime": []}}
        )
        self.reservation_failures = reservation_failures or {}
        self.cancellation_failures = cancellation_failures or {}
        self.stale_final_schedule = deepcopy(stale_final_schedule)
        self.fail_get_schedule_on_calls = fail_get_schedule_on_calls or set()
        self.get_schedule_calls = 0
        self.write_calls: list[tuple[str, list[str] | str]] = []

    async def list_sessions(self) -> AsyncIterator[object]:
        for session in self.sessions:
            yield session

    async def get_schedule(self) -> object:
        self.get_schedule_calls += 1
        if self.get_schedule_calls in self.fail_get_schedule_on_calls:
            raise RuntimeError("fake GetSchedule failure")
        if self.stale_final_schedule is not None and self.write_calls:
            return deepcopy(self.stale_final_schedule)
        return deepcopy(self.schedule)

    async def reserve_sessions(self, session_ids: list[str]) -> ReservationResult:
        if not 1 <= len(session_ids) <= RESERVATION_BATCH_SIZE:
            raise ValueError("fake reservation batch must contain 1 to 10 IDs")
        if len(set(session_ids)) != len(session_ids):
            raise ValueError("fake reservation IDs must be distinct")
        self.write_calls.append(("reserve", list(session_ids)))
        reserved = self.schedule["schedule"]["reserved"]
        result = ReservationResult()
        for session_id in session_ids:
            code = self.reservation_failures.get(session_id)
            if session_id in reserved:
                code = "alreadyScheduled"
            if code:
                result.failed.append(
                    OperationFailure(
                        session_id=session_id,
                        code=code,
                        message=SAFE_FAILURE_MESSAGES.get(
                            code, "Reservation was refused."
                        ),
                    )
                )
            else:
                reserved.append(session_id)
                result.succeeded.append(session_id)
        return result

    async def cancel_reservation(self, session_id: str) -> None:
        from app.clients.events_api import EventsApiError

        self.write_calls.append(("cancel", session_id))
        status = self.cancellation_failures.get(session_id)
        reserved = self.schedule["schedule"]["reserved"]
        if status or session_id not in reserved:
            raise EventsApiError(
                f"Fake cancellation returned HTTP {status or 404}",
                status_code=status or 404,
            )
        reserved.remove(session_id)
