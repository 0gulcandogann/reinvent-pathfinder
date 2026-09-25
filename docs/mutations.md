# M7 safe schedule mutation workflow

## Plan, confirm, execute, verify

`MutationPlanner.build()` compares a normalized current `AttendeeSchedule` with
an `OptimizedSchedule`. It returns a side-effect-free `ScheduleMutationPlan`:
additions, explicit removals, unchanged reservations, replacement pairs, and
warnings. The planner rejects implicit removal of an existing reservation.
An old reservation must be listed in `remove_session_ids` or as the source of
an explicit replacement. Favorites and personal time never become reservation
actions. It validates selected session times, conflicts, and personal time.

`POST /schedule/mutations/plan` exposes that pure planning step. The returned
plan should be shown to the attendee. `POST /schedule/mutations/execute`
requires `confirmed: true`; false or omitted confirmation performs no reads or
writes and returns `confirmation_required`. The executor validates action
structure and reads `GetSchedule` before writing. If the current schedule
differs from the plan's baseline, it returns `stale_plan` with zero writes.
The API rejects live execution unless `AWS_EVENTS_ENABLE_WRITES=true` and an
access token are explicitly configured. `AwsEventsRestClient` also has its own
`enable_writes=False` default. Neither the OAuth helper nor the token presence
alone enables writes. Tests inject `FakeEventsClient` into the API.
The HTTP endpoint currently has no attendee authentication or actor binding.
The write flag must stay disabled on any exposed deployment until that boundary
is added; confirmation and a matching schedule snapshot are not authorization.

## AWS operation mapping

The published [ReserveSessions documentation](https://docs.aws.amazon.com/events/latest/devguide/rest-op-reservesessions.html)
and [OpenAPI schema](https://api.awsevents.com/v1/openapi.json) specify
`POST /v1/events/{eventId}/reservations` with distinct `sessionIds`, 1–10 per
request. The response has `result.successful` and `result.failed`; every
failure includes `sessionId` and `code`, with optional `conflictsWith`.
Pathfinder sends additions in deterministic batches of at most 10 and records
each result. HTTP 200 never implies all IDs succeeded. Unknown failure codes
become a generic refusal without exposing raw response text.

[CancelReservation](https://docs.aws.amazon.com/events/latest/devguide/rest-op-cancelreservation.html)
is one `DELETE /v1/events/{eventId}/reservations/{sessionId}` per reserved
session. HTTP 204 is success; other statuses are per-session failures. A 404
is not treated as a safe blind retry. Writes are not automatically retried,
because a response may be lost after the server applied the operation. The
typed error retains `Retry-After` for caller-controlled retry decisions, but
the executor stops an uncertain reservation batch and reads the schedule.

## Replacement order and verification

For a replacement whose old and new session times do not overlap, Pathfinder
reserves the new session first, reads `GetSchedule`, and cancels the old one
only when the new reservation is both reported successful and present in the
read-back schedule. If the new session is full or the read fails, the old
reservation remains. For an overlapping replacement, the API offers no atomic
swap or temporary hold. Cancelling first could leave the attendee with neither
session, so M7 defers that pair for manual action. Independent explicit
removals can still proceed. This strategy may temporarily hold both sessions
when their times do not conflict; it favors preserving the existing seat.

After cancellation, `GetSchedule` is read again. The final normalized schedule
is the source of truth. Structured `verification_failures` distinguish API
operation failures, reported reservation success missing from the final
schedule, cancellation success still present, missing unchanged commitments,
stale plans, and GetSchedule failures. Successful operations are not rolled
back because another batch or session failed. No automatic fallback booking is
performed.

M7 accepts an already optimized target itinerary; it does not rerun the
optimizer to choose a replacement or automatically book an alternative. A
caller must explicitly prepare a target that omits the old reservation and
name the intended replacement relationship.

## Offline validation and current limits

`python scripts/demo_mutations.py` uses a fake stateful schedule: one reserve
succeeds, one fails as full, and the old nonoverlapping reservation is
cancelled only after replacement verification. Unit tests use mock HTTP
transport and `FakeEventsClient`; no attendee credentials are needed.

Live reservation/cancellation has not yet been validated against reinvent2026
because registered attendee access is unavailable and live write access is
date-gated. Live catalog and schedule validation likewise remain pending
registered re:Invent 2026 attendee access. No live write or attendee API call
was made for M7.
