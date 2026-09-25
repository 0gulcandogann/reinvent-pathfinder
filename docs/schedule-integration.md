# M6 existing attendee schedule integration

## Data flow

`AwsEventsRestClient.get_schedule()` makes one authenticated `GET` request to
`/v1/events/{eventId}/schedule`. It receives its bearer token from the caller;
the OAuth login helper remains separate. The transport returns raw JSON.
`normalize_schedule()` converts that JSON to `AttendeeSchedule`, and
`ExistingSchedulePlanner` combines the normalized schedule with a locally
persisted catalog and `AttendeeProfile`. Search and M3 ranking supply candidate
scores to the existing M4 optimizer; M5 produces explanations. Neither the
planner nor `POST /schedule/optimize-existing` calls AWS.

The published [AWS GetSchedule contract](https://docs.aws.amazon.com/events/latest/devguide/rest-op-getschedule.html)
returns a `schedule` object with `reserved` and `favorites` session-ID arrays
and a `personalTime` array. The adapter maps them as follows:

| AWS field | Pathfinder field | Meaning |
| --- | --- | --- |
| `reserved` | `reserved_session_ids` | Existing commitments; mandatory fixed sessions |
| `favorites` | `favorite_session_ids` | Interest metadata only; does not occupy time or add a score bonus |
| `personalTime` | `personal_time` | Hard blocked intervals |

The adapter requires all three arrays to be present and correctly typed. This
is deliberate: treating a malformed or partial schedule as empty could discard
existing commitments. It accepts absent optional personal-time title,
description, and location. Personal-time IDs and start/end times are required.
AWS's offsetless personal-time timestamps are UTC in the published schema, so
the adapter attaches UTC before converting them to event-local time. Invalid
intervals fail validation.

## Commitments and provenance

The planner resolves every reserved ID against the local SQLite catalog. It
fails if any reserved session is missing, invalid, outside the requested event
date window, or incompatible with another hard constraint. This keeps existing
commitments visible rather than silently dropping them. Reserved sessions are
passed to M4 as `fixed_sessions`. Personal time is split at local calendar
midnights and merged into the profile's date-specific blocked times. The
original profile and schedule are not mutated. Favorites remain metadata,
including for rejected sessions.
An identical attendee weekday block and personal-time date block are counted
once for the same event date and clock interval.

The response carries `session_items` with `existing_reserved` or
`pathfinder_selected` provenance, `personal_time_items` with `personal_time`
provenance, plus `already_reserved_ids` and `proposed_addition_ids`. These
separate current commitments from proposed additions for the M7 mutation
planner. The response also includes the unchanged M4 `schedule` and M5
`explanation`; rejected candidates expose conflict reasons and selected IDs
where M4 can identify them. Venue transitions include fixed sessions.

## Offline use and validation

The API accepts a normalized `existing_schedule` payload. It does not fetch
the attendee schedule itself. A caller with attendee access can later read
GetSchedule, normalize it, and pass it to the planner or API. Use
`python scripts/demo_existing_schedule.py` to see the fixture scenario with
Monday reserved sessions, Tuesday personal time, and favorites. The demo uses
`FakeEventsClient` and a temporary SQLite catalog. Tests mock REST transport
and exercise the adapter, planner, endpoint, provenance, and hard constraints
without attendee credentials.

The planner uses the event timezone `America/Los_Angeles` by default; callers
may supply another IANA timezone. Aware catalog session times are converted to
that event clock for optimization without changing stored sessions. Its
personal-time blocks are specific to
calendar dates, so an attendee block does not recur every week. M4 currently
does not schedule overnight sessions or model travel buffers. Missing reserved
IDs require a complete, current local catalog or explicit resolution; M6 does
not fetch missing sessions from AWS. Favorites do not change scores in M6.
This integration endpoint performs no schedule writes.

**Live AWS schedule validation requires registered re:Invent 2026 attendee
access and is pending.** OAuth has already been validated, but the current
Builder ID is not registered for `reinvent2026`; no live API retry is part of
M6.
