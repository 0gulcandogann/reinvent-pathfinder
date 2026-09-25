# M5 deterministic schedule explanations

## Data flow

`POST /schedule/explain` runs the same local M3 search and M4 optimizer as
`POST /schedule/optimize`, then passes the unchanged `OptimizedSchedule` and
`AttendeeProfile` to `explain_schedule`. The optimizer objective is unchanged.
The new endpoint returns both `schedule` and `explanation`; the existing
optimize endpoint keeps its M4 response shape.

For each selected session, the explanation copies M3's text score, query
terms, field scores, matched preferences, bonuses, and penalties. It uses
M4's selected order, fixed flags, local times, and rejected conflict IDs to
describe schedule fit and displaced candidates. Venue messages are derived
from consecutive known-venue sessions on each event-local day, using M4's
2-point transition penalty only when venue minimization is enabled. Missing
venues never create a penalty. No LLM or new relevance scorer is involved.

Rejection messages translate M4 reason codes into attendee-readable text.
`lower_total_utility` is presented as `lower_total_schedule_utility`. A time
conflict names the selected sessions involved. A rejection means a particular
schedule was preferred under current constraints and weights; it does not
judge a session's intrinsic quality.

## Goal coverage formula

Coverage is calculated separately for every profile interest and learning
goal that M3 recorded in `matched_preferences`. The candidate pool is the
sessions considered by M4: selected sessions plus rejected candidates that
were individually schedulable. Candidates rejected for blocked or fixed time,
invalid/mixed/cross-day time, or event dates are excluded. Candidates outside
the configured candidate cap are also excluded.

For each interest or goal:

1. Use each matching candidate's nonnegative M3 `SearchHit.score` as its
   opportunity value. This reuses existing text and preference evidence.
2. Set `K = max(1, number of selected sessions)`. The available opportunity
   score is the sum of the top `K` matching candidate values.
3. The selected opportunity score is the sum of matching selected-session
   values. Coverage is `round(100 * selected / available)`, clamped to
   `0..100`. If available is zero, show 0 with `no_opportunity` status.

The API also exposes both sums, matched session IDs, candidate count, and
status so the percentage can be checked. This is Pathfinder's relative
schedule-scoring estimate, **not an objective measure of learning**. The
denominator ignores conflict combinations, so it can include opportunities
that could not all fit together. A fixed session outside the ranked pool has
no M3 match evidence and contributes zero until it is ranked.

## Schedule insights

Structured metrics include per-day session counts, per-day and total known
venue transitions, selected utility, fixed count, blocked-period count and
minutes, blocked candidate exclusions, days at the daily maximum, and
candidate-cap exclusions. Blocked minutes sum the configured intervals;
overlapping blocks are not merged. Messages are short statements derived from
these counts.

A rejected time or fixed-session conflict is considered *high scoring* when
its M3 score is at least 75% of the highest positive score in the considered
optimizer pool, rounded up. This relative threshold is a display rule, not
part of optimization. If the pool has no positive scores, the count is zero.

When the candidate cap excludes sessions, the explanation endpoint retrieves
up to 20 immediately following M3-ranked results and marks them
`candidate_cap`. The metric reports the full number outside the cap, while
the rejection list shows at most 20 examples. The optimizer still receives
only the configured top `candidate_limit` candidates (default 150).

## Limits

Explanations describe the deterministic M3/M4 model as implemented. They do
not infer attendee intent, prove learning outcomes, add travel-time rules, or
claim that a candidate outside the capped pool was evaluated for schedule
fit. Existing attendee schedules are supported offline through M6;
live AWS REST/MCP attendee validation remains pending because this Builder ID
is not registered for re:Invent 2026.
