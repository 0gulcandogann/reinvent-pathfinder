# Current deterministic scoring

Local search scores each distinct query token once, using its strongest
matching field: title 12; service/topic 8; track/role 5; abstract 2;
speaker 1. Results with equal total score sort by casefolded title, then
stable session ID. Filters apply before scoring.

An optional attendee profile adds explicit preference contributions: interest
4 (up to two), preferred service 5, preferred topic 4, desired level 3,
preferred session type 3, learning goal 4 (up to two), and depth 1 for Level
300 or 3 for Level 400. An avoided level subtracts 6. The final M3 score is
text relevance plus preference score. See [README](../README.md) for examples.

M4 maximizes the sum of these scores under hard time, fixed-session, blocked
time, and daily-count constraints. When venue minimization is enabled, each
known venue transition costs 2 points. See [optimizer](optimizer.md) for the
exact objective and limitations. M5 explanations copy these scores rather
than recalculating them; see [explainability](explainability.md).
