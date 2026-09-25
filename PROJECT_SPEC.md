# re:Invent Pathfinder

> Your intelligent route through AWS re:Invent.

## 1. Product Vision

re:Invent Pathfinder is an intelligent conference planner for AWS re:Invent 2026.

Instead of simply recommending sessions, Pathfinder builds a complete attendee itinerary based on:

- technical interests
- skill level
- learning goals
- existing reservations
- favorites
- personal time
- schedule conflicts
- session availability
- venue/location changes
- attendee preferences

The goal is to answer:

> “Given everything I care about, what is the best way for me to spend re:Invent?”

The product should behave as a **conference optimization engine**, not merely a chatbot.

---

# 2. Core User Story

Example input:

> I'm a platform engineer interested in serverless, observability and security.
>
> Prefer Level 300–400 sessions.
>
> Keep Tuesday afternoon free.
>
> Avoid unnecessary venue changes.
>
> I care more about deep technical sessions than product announcements.

Pathfinder should:

1. understand these preferences
2. analyze the re:Invent catalog
3. rank relevant sessions
4. resolve time conflicts
5. account for personal time
6. generate an optimized itinerary
7. explain why each session was selected
8. provide alternatives
9. optionally favorite/reserve selected sessions
10. verify resulting schedule

---

# 3. Hackathon Goal

Optimize for all four judging dimensions.

## Creativity

Build a constraint-aware conference planner rather than a generic session recommendation chatbot.

## Utility

Solve real re:Invent attendee problems:

- too many sessions
- conflicting sessions
- difficult discovery
- varying technical depth
- overloaded days
- poor backups when sessions fill
- unnecessary venue movement

## Technical Depth

Demonstrate:

- AWS Events REST API
- AWS Events MCP server
- catalog ingestion
- local search
- semantic ranking
- deterministic scoring
- constraint optimization
- schedule mutations
- plan → execute → verify workflow

## Project Quality

Deliver:

- polished web UI
- architecture diagram
- strong README
- reproducible setup
- tests
- example scenarios
- short demo video
- clear Builder Center write-up

---

# 4. Non-Goals

Do NOT initially build:

- social networking
- attendee matching
- chat between attendees
- generic re:Invent FAQ bot
- maps/navigation engine
- mobile native application
- complex multi-user backend
- autonomous reservation changes without user confirmation

Keep the first version focused on:

> Build the best possible personal re:Invent schedule.

---

# 5. Product Principles

## Explainable

Never output only:

> “Attend SEC401.”

Instead:

> Recommended because it matches Security + Serverless, is Level 400, does not conflict with your current schedule, and keeps you in the same venue as your previous session.

## Deterministic where possible

LLMs may interpret user intent.

Scheduling decisions should primarily be made using deterministic scoring and optimization.

## Safe mutations

Never silently modify the attendee schedule.

Use:

```text
PLAN
↓
SHOW CHANGES
↓
USER CONFIRMATION
↓
EXECUTE
↓
GET SCHEDULE
↓
VERIFY
```

## Graceful degradation

The application must remain useful before reservation write access becomes available.

---

# 6. AWS Events API

Target event:

```text
reinvent2026
```

Relevant REST operations:

```text
ListEvents
GetEvent

ListSessions
GetSession

GetSchedule

AssociateFavorites
DisassociateFavorite

CreatePersonalTime
UpdatePersonalTime
DeletePersonalTime

ReserveSessions
CancelReservation
```

The MCP server exposes equivalent tools.

Important implementation rules:

- `ListSessions` is paginated.
- Never assume a short page is the final page.
- Continue until `nextToken` is absent.
- Session fields must be treated defensively because fields may be optional.
- The API does not provide catalog search/filtering.
- Pathfinder therefore owns search, ranking and filtering.
- `GetSchedule` is the source of truth for attendee schedule data.
- Always verify schedule mutations by reading the schedule again.
- Reservation operations may partially succeed.
- HTTP success does not necessarily mean every requested reservation succeeded.
- Reservation failures must be handled per session.
- Respect throttling and `Retry-After`.

Reservation/cancel support should be feature-flagged until write access becomes available.

---

# 7. Architecture

```text
                    ┌──────────────────────┐
                    │ AWS Events REST API  │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ Catalog Ingestion    │
                    │ + Normalization      │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ Local Session Store  │
                    │ + Search Index       │
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
        Keyword Search    Semantic Search    Filters
              │                │                │
              └────────────────┼────────────────┘
                               ▼
                    ┌──────────────────────┐
                    │ Candidate Ranking    │
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ Schedule Optimizer   │
                    │ Constraint Solver    │
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ Explanation Engine   │
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │ Web Application      │
                    └──────────┬───────────┘
                               │
                 user confirms mutation
                               │
                               ▼
               ┌──────────────────────────┐
               │ REST API / MCP Actions   │
               └─────────────┬────────────┘
                             ▼
                     GetSchedule Verify
```

---

# 8. Technology Stack

Prefer a boring, maintainable stack.

## Application

```text
Python 3.13+
FastAPI
Pydantic
httpx
```

## Frontend

```text
Next.js
TypeScript
Tailwind CSS
```

Avoid spending excessive time building a design system.

## Search

Phase 1:

```text
local normalized catalog
keyword scoring
taxonomy scoring
```

Phase 2:

```text
embeddings
semantic similarity
```

Do not require a vector database for MVP.

For this catalog size, an in-memory/local solution is preferable until proven otherwise.

## Optimization

Start with custom deterministic constraint logic.

Move to:

```text
Google OR-Tools
```

only if optimization complexity justifies it.

Do not prematurely introduce a solver.

## Storage

MVP:

```text
SQLite
```

Potential deployment:

```text
DynamoDB
```

But Pathfinder should not require DynamoDB simply to look “more AWS”.

Use AWS services when they improve the architecture.

---

# 9. Repository Structure

```text
reinvent-pathfinder/
│
├── apps/
│   ├── api/
│   │   ├── app/
│   │   │   ├── api/
│   │   │   ├── clients/
│   │   │   │   ├── events_api.py
│   │   │   │   └── events_mcp.py
│   │   │   ├── catalog/
│   │   │   ├── ranking/
│   │   │   ├── optimizer/
│   │   │   ├── schedule/
│   │   │   ├── models/
│   │   │   └── main.py
│   │   │
│   │   └── tests/
│   │
│   └── web/
│       ├── app/
│       ├── components/
│       └── lib/
│
├── data/
│   └── .gitkeep
│
├── docs/
│   ├── architecture.md
│   ├── scoring.md
│   └── demo.md
│
├── scripts/
│   └── sync_catalog.py
│
├── .env.example
├── README.md
├── PROJECT_SPEC.md
└── LICENSE
```

---

# 10. Domain Models

## Session

Normalize the upstream AWS session object.

```python
class Session:
    id: str
    code: str | None

    title: str
    abstract: str | None

    session_type: str | None
    level: str | None

    tracks: list[str]
    topics: list[str]
    industries: list[str]
    roles: list[str]
    services: list[str]

    speakers: list[str]

    start_at: datetime | None
    end_at: datetime | None

    venue: str | None
    room: str | None

    reservable: bool
    availability: str | None
```

Do not tightly couple internal models to raw AWS JSON.

Create:

```text
AWS response
    ↓
adapter
    ↓
Pathfinder domain model
```

---

# 11. User Preference Model

```python
class AttendeeProfile:
    interests: list[str]

    preferred_services: list[str]
    preferred_topics: list[str]

    desired_levels: list[str]
    avoided_levels: list[str]

    preferred_session_types: list[str]

    learning_goals: list[str]

    blocked_times: list[TimeBlock]

    max_sessions_per_day: int | None

    minimize_venue_changes: bool

    prioritize_depth: bool

    diversity_weight: float
```

Natural language may be converted into this structure.

Example:

```text
"I want advanced serverless and observability talks,
but keep Tuesday afternoon free."
```

becomes:

```json
{
  "interests": [
    "serverless",
    "observability"
  ],
  "desired_levels": [
    "300",
    "400"
  ],
  "blocked_times": [
    {
      "day": "Tuesday",
      "start": "12:00",
      "end": "17:00"
    }
  ]
}
```

---

# 12. Session Scoring

Every candidate receives a score.

Initial model:

```text
score =
    interest_match
  + service_match
  + topic_match
  + level_match
  + role_match
  + session_type_match
  + semantic_similarity
  + schedule_fit
  + venue_bonus
  - conflict_penalty
  - venue_switch_penalty
  - overload_penalty
```

Suggested normalized range:

```text
0–100
```

Example breakdown:

```text
SVS401

Interest match          +24
Service match           +18
Level preference        +15
Learning goal match     +19
Same venue              + 6
Semantic relevance      +14
Conflict                 + 0
--------------------------------
Total                     96
```

The UI should expose a simplified explanation.

---

# 13. Hard vs Soft Constraints

## Hard constraints

Never violate:

```text
session time conflict
personal-time conflict
session outside event dates
explicitly blocked time
```

## Soft constraints

Optimize:

```text
technical relevance
level
venue switching
session diversity
daily workload
learning-goal coverage
session type
availability
```

This distinction is important.

A Level 400 preference can be broken.

Two simultaneous sessions cannot.

---

# 14. Optimizer

Input:

```text
candidate sessions
+
user profile
+
existing schedule
+
personal time
```

Output:

```python
OptimizedSchedule(
    selected_sessions=[],
    rejected_sessions=[],
    alternatives={},
    score=float,
    warnings=[]
)
```

The optimizer should consider the entire week rather than greedily selecting the highest-ranked individual sessions.

Example:

```text
Session A score: 97
Session B score: 93
Session C score: 91
```

If choosing A prevents attending both B and C:

```text
B + C
```

may represent the better itinerary.

This distinction is central to Pathfinder.

---

# 15. Schedule Resilience

Every important schedule slot should have alternatives.

Example:

```text
14:00

PRIMARY
SVS401
Advanced Serverless Architecture

BACKUP #1
CON325
Containers at Scale

BACKUP #2
COP310
Advanced Observability Patterns
```

Each backup should have:

```text
similarity score
schedule compatibility
venue impact
learning-goal impact
```

Example:

```text
SVS401 unavailable.

Suggested replacement:

CON325

Learning-plan retention: 91%
No time conflict
Same venue
Level 300
```

Do NOT initially auto-book the replacement.

Ask for confirmation.

---

# 16. Learning Goal Coverage

The schedule should represent goals across the week.

Example:

```text
Serverless       92%
Security         75%
Observability    84%
Containers       41%
```

This is not meant as scientific precision.

It is an understandable visualization of how well the generated schedule covers the attendee's stated priorities.

Use the underlying session scores to produce it.

---

# 17. Daily Schedule Health

Pathfinder should identify problems such as:

```text
Tuesday has 8 sessions.
```

```text
You change venue 5 times Wednesday.
```

```text
Security is one of your top priorities,
but Thursday contains no security sessions.
```

```text
You have no break between 09:00 and 17:00.
```

Call these:

```text
Schedule Insights
```

Avoid presenting them as absolute judgments.

---

# 18. Natural Language Assistant

Example:

```text
Make Tuesday less busy.
```

Interpretation:

```text
reduce daily session count
preserve highest-value sessions
re-run optimizer for Tuesday
```

Example:

```text
Replace my Wednesday 2 PM session
with something more advanced about containers.
```

Process:

```text
intent extraction
↓
identify current session
↓
find candidates
↓
apply constraints
↓
rank replacements
↓
show proposed mutation
↓
confirmation
↓
execute
↓
GetSchedule
↓
verify
```

The LLM must not directly mutate schedule state.

It produces structured intent.

Application logic executes it.

---

# 19. Structured Agent Actions

Prefer structured actions such as:

```python
SearchSessions
RecommendSessions
OptimizeSchedule
ExplainSession
SuggestReplacement
FavoriteSession
ReserveSession
CancelReservation
BlockPersonalTime
```

Avoid a giant unconstrained:

```python
run_agent(prompt)
```

function controlling everything.

---

# 20. REST vs MCP

Use both deliberately.

## REST

Best for:

```text
bulk catalog synchronization
application backend
deterministic reads
schedule synchronization
```

## MCP

Best for:

```text
agent demonstration
natural-language interaction
tool-use workflow
```

The product should demonstrate that Pathfinder understands both interfaces without duplicating business logic.

Business rules belong inside Pathfinder.

Not inside the REST client.

Not inside the MCP client.

---

# 21. Mutation Workflow

All mutations:

```text
REQUEST
   ↓
PLAN
   ↓
VALIDATE
   ↓
SHOW USER
   ↓
CONFIRM
   ↓
EXECUTE
   ↓
GET SCHEDULE
   ↓
VERIFY
   ↓
DISPLAY RESULT
```

Example:

```text
Proposed changes

REMOVE
SEC201

ADD
SVS401

Reason
SVS401 better matches your advanced serverless goal.

Schedule conflicts
None

Proceed?
```

---

# 22. Partial Failure Handling

Reservation requests can succeed for some sessions and fail for others.

Never treat the entire request as successful solely based on HTTP status.

Expected application model:

```python
class ReservationResult:
    succeeded: list[str]
    failed: list[ReservationFailure]
```

Possible UI:

```text
2 of 3 sessions reserved.

✓ SVS401
✓ SEC330

✗ COP402
Session full

Recommended backup:
COP310
```

Then:

```text
GetSchedule
```

must confirm final state.

---

# 23. API Rate Limits

Implement:

```text
request throttling
Retry-After support
bounded retries
exponential backoff where appropriate
```

Do not aggressively repeatedly poll the API.

Catalog data should normally be cached locally.

---

# 24. API Client Requirements

Create a clean interface:

```python
class EventsClient(Protocol):

    async def list_sessions(...):
        ...

    async def get_schedule(...):
        ...

    async def reserve_sessions(...):
        ...

    async def cancel_reservation(...):
        ...

    async def add_favorites(...):
        ...

    async def create_personal_time(...):
        ...
```

Implement:

```text
AwsEventsRestClient
```

Potentially later:

```text
AwsEventsMcpClient
```

Tests should be able to substitute:

```text
FakeEventsClient
```

No unit test should require the real API.

---

# 25. Catalog Synchronization

Command:

```bash
python scripts/sync_catalog.py
```

Expected behavior:

```text
fetch page
↓
normalize
↓
store
↓
follow nextToken
↓
repeat
↓
build indexes
```

Output:

```text
Fetched: 2,xxx sessions
Normalized: 2,xxx
Skipped: x
Errors: x
```

Never terminate pagination because a page contains fewer records than expected.

---

# 26. Search

MVP search combines:

```text
title
abstract
services
topics
tracks
roles
speakers
```

Example:

```text
"advanced lambda cold starts"
```

Potential matches:

```text
Lambda performance
Serverless architecture
Runtime optimization
Observability
```

Search results should be independent from schedule optimization.

Architecture:

```text
SEARCH
→ candidates

RANKING
→ relevance

OPTIMIZER
→ itinerary
```

---

# 27. UI

Primary screens:

## Onboarding

```text
What do you want to get out of re:Invent?
```

Collect:

```text
interests
technical level
roles
AWS services
session types
schedule intensity
venue preference
```

---

## Discover

```text
Search sessions
Filter
Explain recommendation
Favorite
```

---

## My Plan

Weekly timetable.

Example:

```text
MONDAY

09:00  SVS301
10:30  SEC402
12:00  BREAK
13:00  CON305
15:00  COP401
```

---

## Optimize

Controls:

```text
Optimize my week
Reduce venue changes
Make schedule less busy
Increase technical depth
Improve Security coverage
```

---

## Insights

Example:

```text
Learning Goals

Serverless       █████████░
Security         ███████░░░
Observability    ████████░░
Containers       █████░░░░░
```

---

# 28. MVP

MVP is complete when this works:

```text
sync catalog
↓
enter preferences
↓
search/rank sessions
↓
generate conflict-free itinerary
↓
show explanations
↓
show alternatives
```

No reservation support is required for MVP completion.

---

# 29. Milestone Plan

## M0 — Repository

Build:

```text
repo structure
FastAPI
Next.js
pytest
linting
formatting
CI
```

Success:

```text
API starts
UI starts
tests pass
```

---

## M1 — Catalog

Build:

```text
AWS client
pagination
normalization
SQLite persistence
sync command
```

Success:

```text
full catalog can be downloaded
and queried locally
```

---

## M2 — Search

Build:

```text
keyword search
taxonomy filters
ranking
```

Success:

```text
query:
"advanced serverless observability"

returns useful results
```

---

## M3 — Preferences

Build structured:

```text
AttendeeProfile
```

Add onboarding UI.

Success:

```text
user preferences influence ranking
```

---

## M4 — Optimizer

Build:

```text
time conflict detection
blocked time
daily load
venue penalty
weekly optimization
```

Success:

```text
Generate Schedule
```

returns a valid conflict-free itinerary.

This is the first major demo milestone.

---

## M5 — Explainability

Build:

```text
score breakdown
Why this session?
schedule insights
learning-goal coverage
```

Success:

Every recommendation can answer:

```text
Why was this chosen?
```

---

## M6 — Real Schedule Integration

Build:

```text
GetSchedule
favorites
personal time
```

Success:

Pathfinder combines:

```text
AWS schedule
+
Pathfinder recommendations
```

without destroying existing attendee data.

---

## M7 — Reservation Support

Enable when API write access becomes available.

Build:

```text
reserve
cancel
partial failures
fallback recommendations
GetSchedule verification
```

Success scenario:

```text
reserve primary
↓
primary full
↓
show backup
↓
user confirms
↓
reserve backup
↓
verify
```

---

## M8 — MCP Agent

Build natural-language interface.

Demo:

```text
Replace my Tuesday afternoon session
with something more advanced about security.
```

Pathfinder:

```text
understands
plans
explains
asks
executes
verifies
```

---

## M9 — Polish

Build:

```text
loading states
error states
screenshots
architecture diagram
README
demo script
Builder Center project
```

---

# 30. Testing Strategy

## Unit Tests

Must cover:

```text
pagination
normalization
time overlap
ranking
hard constraints
soft constraints
venue penalty
daily limits
fallback selection
partial reservation results
```

---

## Golden Scenario Tests

Create fixtures representing realistic attendees.

### Persona A

```text
Serverless Engineer

Goals:
Lambda
Event-driven architecture
Observability

Level:
300–400
```

### Persona B

```text
Security Engineer

Goals:
IAM
Security architecture
Containers

Level:
300–400
```

### Persona C

```text
New AWS User

Goals:
Architecture fundamentals
Serverless
Databases

Level:
100–200
```

Generated schedules should differ substantially.

---

# 31. Critical Tests

Codex must implement these early.

### Conflict

Two sessions:

```text
10:00–11:00
10:30–11:30
```

Both can never appear in the final itinerary.

### Blocked Time

Personal time:

```text
13:00–15:00
```

No generated session may overlap.

### Global Optimization

```text
A score 100
B score 70
C score 70
```

A conflicts with both B and C.

B and C do not conflict.

Optimizer should be capable of selecting:

```text
B + C
```

when total schedule utility is greater.

### Venue Penalty

Two otherwise equal schedules.

Prefer the one requiring fewer unnecessary venue changes when:

```text
minimize_venue_changes = true
```

---

# 32. Demo Scenario

The final demo should avoid generic:

```text
"Find Lambda sessions."
```

Use:

> I'm a platform engineer focused on serverless, security and observability.
>
> I prefer Level 300 and 400 sessions.
>
> Keep Tuesday afternoon free and avoid unnecessary venue changes.
>
> Build my week.

Show:

```text
catalog analysis
↓
optimized itinerary
↓
goal coverage
↓
reasoning
↓
alternatives
```

Then:

> Make Wednesday less busy.

Show schedule re-optimization.

Then:

> Replace this session with something more advanced about security.

Show replacement.

Final reservation demo:

```text
reserve
↓
failure/full if available
↓
fallback
↓
confirmation
↓
verification
```

---

# 33. Differentiator

The central positioning:

> Most conference assistants help you find sessions.
>
> Pathfinder optimizes your entire conference.

Do not lose this distinction.

---

# 34. README Story

README should communicate within the first screen:

```text
re:Invent has thousands of possible sessions.

Choosing individually relevant sessions is easy.

Building a coherent week is not.

Pathfinder treats re:Invent planning as an optimization problem.
```

Then show:

```text
input
→ optimization
→ final itinerary
```

before explaining implementation details.

---

# 35. Metrics for Demo

Pathfinder can calculate:

```text
number of conflicts prevented
goal coverage
average session relevance
venue switches
sessions per day
backup coverage
```

Example:

```text
Before optimization

7 conflicts
11 venue transitions
61% goal coverage


After optimization

0 conflicts
5 venue transitions
89% goal coverage
```

Do not claim universal improvement.

These metrics describe the generated schedule under the selected preferences.

---

# 36. Coding Rules for Codex

Codex must:

1. Read this file before significant architectural changes.
2. Prefer small focused modules.
3. Add tests with each feature.
4. Avoid speculative abstractions.
5. Keep AWS API code isolated from domain logic.
6. Never couple optimizer code to HTTP handlers.
7. Never require the real AWS API for unit tests.
8. Treat upstream API fields defensively.
9. Preserve type safety.
10. Run formatting, linting and tests before completing a task.

Do not refactor unrelated modules unless necessary.

---

# 37. First Codex Task

Implement only **M0 + the initial M1 foundation**.

Specifically:

```text
Create repository structure.

Create FastAPI application.

Create health endpoint.

Define Session domain model.

Define EventsClient protocol.

Create AwsEventsRestClient.

Implement ListSessions pagination.

Create FakeEventsClient.

Add normalization layer.

Add tests for:

- pagination
- missing optional fields
- malformed session handling
- network/API errors

Create scripts/sync_catalog.py.

Do NOT implement:
- LLM
- embeddings
- optimizer
- MCP
- reservation
- frontend design
```

Definition of done:

```bash
pytest
```

passes.

And:

```bash
python scripts/sync_catalog.py
```

can walk all available catalog pages using the configured attendee authentication.

---

# 38. Next Task

Only after M1 is clean:

```text
Implement local persistence and search.
```

Do not jump ahead.

---

# 39. Final Product Statement

re:Invent Pathfinder is not:

```text
an AI chatbot for the conference catalog
```

It is:

```text
an intelligent scheduling and optimization layer
on top of the AWS Events API.
```

Every architectural and product decision should reinforce that idea.