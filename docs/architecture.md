# Current architecture (M0–M9)

```mermaid
flowchart TD
    REST[AWS Events REST] --> CN[Catalog normalization]
    MCP[AWS Events MCP] --> CN
    Fake[Offline fake client] --> CN
    REST --> SN[Schedule normalization]
    MCP --> SN
    Fake --> SN
    CN --> DB[SQLite catalog repository]
    DB --> Search[Local search and M3 ranking]
    Search --> Optimizer[M4 deterministic optimizer]
    Optimizer --> Explain[M5 explanations]
    SN --> Integration[M6 existing schedule integration]
    Integration --> Optimizer
    Optimizer --> Planner[M7 mutation planner]
    Planner --> Executor[M7 confirmed executor]
    Executor --> Verify[GetSchedule verification]
    Agent[M8 typed-intent agent] --> Search
    Agent --> Integration
    Agent --> Explain
    Agent --> Planner
    Agent --> Executor
    API[FastAPI routes] --> Agent
    API --> Search
    API --> Optimizer
    API --> Planner
    API --> Executor
```

Core ranking, time constraints, optimization, and explanations are independent
of FastAPI, SQLite, OAuth, and AWS transport schemas. REST and MCP adapters
only supply catalog/schedule data and execute explicitly authorized operations.
The OAuth helper is separate from the REST client. The catalog sync completes
the upstream walk before atomically replacing the SQLite generation; an
all-malformed generation also preserves the last known-good catalog.

The API's agent context is process-local and keyed by `conversation_id`.
It is suitable for offline demonstration, not authenticated multi-user use.
Live writes are disabled by default. See [mutation safety](mutations.md) and
[agent boundaries](agent.md) before deploying a write-enabled API.
M9's explicit demo mode seeds a separate fixture SQLite catalog and uses a
stateful fake Events client; reset restores that fake and clears conversations.

Live AWS REST/MCP attendee validation remains pending because this Builder ID
is not registered for re:Invent 2026. Live reservation/cancellation validation
is separately date/access gated.
