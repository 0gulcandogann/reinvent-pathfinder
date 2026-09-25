# Offline demos

Each command uses local fixtures and requires no AWS attendee or LLM account.

For the M9 product UI, follow [the README setup](../README.md#run-the-offline-product-ui).
Its Plan, Why this?, Insights, Assistant, proposed mutation, and verified
result states are the six Builder Center screenshot opportunities. The
**Reset demo** control restores the original fake schedule and conversation.
`python scripts/smoke_ui.py` exercises the same offline HTTP flow with both
servers running.

The [Demo Plan image](assets/pathfinder-demo-plan.png) shows the fixture-backed
product UI and mode switch. The [Live access image](assets/pathfinder-live-access.png)
shows the sign-in gate before attendee data is available. Run the local demo to
inspect the explanation, insights, assistant, mutation proposal, and verified
result states.

| Command | Shows |
| --- | --- |
| `python scripts/demo_search.py` | SQLite catalog search |
| `python scripts/demo_personas.py` | Profile-aware ranking |
| `python scripts/demo_optimizer.py` | Conflict-free weekly optimization |
| `python scripts/demo_explanations.py` | Selection reasons and goal coverage |
| `python scripts/demo_existing_schedule.py` | Reserved sessions, favorites, and personal time |
| `python scripts/demo_mutations.py` | Plan, confirm, partial result, GetSchedule verify |
| `python scripts/demo_agent.py` | Typed intents, follow-ups, fake MCP, confirmed mutation |

The live catalog command is `python scripts/sync_catalog.py --login`, but live
AWS REST/MCP attendee validation remains pending because this Builder ID is
not registered for re:Invent 2026. Live reservation/cancellation validation
is separately date/access gated. Do not use a live write flow for demos.
