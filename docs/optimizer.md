# M4 deterministic schedule optimizer

## Input and objective

`POST /schedule/optimize` searches the local SQLite catalog with the M3
query, filters, and `AttendeeProfile`. It passes the ranked `SearchHit` objects
to the optimizer. It never calls AWS. Fixed sessions can be supplied as
normalized `Session` objects; if one also appears among the ranked candidates,
its M3 score is retained. A fixed session outside the ranked pool has score 0.

For a selected itinerary, the objective is:

```text
sum(M3 SearchHit.score)
  - 2 * known-venue transitions (only if minimize_venue_changes is true)
```

`SearchHit.score` already includes M3 text relevance and attendee preference
contributions. There is no new relevance formula. A transition is counted
between consecutive selected sessions on the same day whose known venues
differ. An unknown venue creates no penalty; the last known venue is retained
for comparing later sessions. The penalty is 2 points per transition, smaller
than a title match (12 points). If venue minimization is disabled, the penalty
is zero and venue never affects selection or tie-breaking. Ties in objective
prefer fewer sessions, then lexicographically smaller session ID sequences.

## Hard constraints

- Sessions use half-open intervals: `[start, end)`. A session ending at 11:00
  is compatible with one starting at 11:00.
- Selected sessions cannot overlap each other, a fixed session, or a matching
  blocked weekday/date and local clock interval.
- `max_sessions_per_day` limits the count, including fixed sessions.
- M8 can pass an optional date-specific daily limit when an attendee asks to
  make one day lighter. The limit remains a hard M4 constraint and does not
  change the utility objective.
- Every fixed session is mandatory. Contradictory fixed sessions or fixed
  sessions violating explicit constraints produce a validation error.
- Missing, nonpositive, mixed-awareness, and cross-midnight candidate times
  are rejected with reasons. An optional event date window excludes sessions
  outside it. Fixed sessions with those problems produce a validation error.

Aware datetimes are compared in a common event timezone selected from the
first fixed session, or the first aware candidate by ID. Their original
timezone-aware values remain in the returned `Session`. If fixed sessions are
naive, aware candidates are rejected; otherwise, when candidates mix naive
and aware times, aware candidates set the event time mode and naive candidates
are rejected. Blocked times are interpreted as wall-clock times in that event
timezone. A blocked `day` can be a full weekday name or ISO date.

## Algorithm and candidate size

The API ranks the local catalog, then takes the top `candidate_limit` hits in
M3 score order. The default is 150; the request can set 1–500. The cap is
deterministic and configurable. Results outside this pool cannot be selected.

Sessions are grouped by event-local calendar day after invalid candidates are
removed. Each day is a weighted interval directed acyclic graph ordered by
end time. A dynamic program tracks the last selected session, selected count,
last known venue, and whether mandatory fixed nodes have been traversed.
Edges connect compatible sessions. It compares complete plans, so the
100-point A versus two compatible 70-point B/C case selects B+C. Day plans
are combined into a weekly itinerary because M4's hard and soft constraints
do not couple different days.

For `n` candidates on a day, daily cap `K`, and `V` distinct venue states,
the worst-case time is `O(n² K V)` and state storage is `O(n K V)`, excluding
the stored path tuples. The API candidate cap bounds this cost. The offline
fixture and test sets are small; no solver dependency is needed for these
constraints. An offline audit with 150 synthetic candidates spanning two
calendar days and a daily cap of eight took 49.5 ms for one optimizer call
on the development machine. This is a single measurement, not a latency
guarantee; an uncapped, same-day pool can take longer.

## Output and limitations

Each selected session includes its M3 score breakdown and whether it was
fixed. Rejected candidates have explicit reasons and conflicting selected
IDs where relevant. The response also includes total utility, relevance
sum, venue penalty, transition count, daily counts, constraints, and factual
warnings. Alternatives are positive-scoring rejected sessions that overlap
one selected nonfixed session and could replace it without conflicting with
the rest of the selected itinerary. They are not automatically booked.

This optimizer does not model travel duration, buffers, capacity, session
availability, recurring multi-day blocks, overnight sessions, cross-day
preferences, or reservation state. It optimizes exactly the constraints and
objective above; it does not claim optimality for omitted considerations.
