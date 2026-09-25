import assert from "node:assert/strict";
import test from "node:test";
import { EMPTY_PROFILE, levelsForDepth, profileForRequest, toggleValue } from "../lib/profile.ts";
import { agentErrorMessage, builderIdLabel, builderIdNotice, coverageTopic, mutationCanConfirm, mutationOutcome, provenanceLabel, safeErrorMessage } from "../lib/view.ts";
import { daysOfWeek, explanationEvidence, scheduleDayEntries } from "../lib/schedule-view.ts";
import type { AgentResponse, IntegratedSchedule, MutationExecutionResult, ScheduleMutationPlan, SessionExplanation } from "../lib/types.ts";

test("onboarding depth and profile serialization use the backend profile fields", () => {
  assert.deepEqual(levelsForDepth("explore"), ["100", "200"]);
  assert.deepEqual(levelsForDepth("intermediate"), ["200", "300"]);
  assert.deepEqual(levelsForDepth("deep"), ["300", "400"]);
  const profile = profileForRequest({
    ...EMPTY_PROFILE,
    interests: ["serverless"], desired_levels: levelsForDepth("deep"),
    blocked_times: [{ day: "Tuesday", start: "13:00:00", end: "17:00:00" }],
    learning_goals: [" observability ", ""],
  });
  assert.deepEqual(profile.learning_goals, ["observability"]);
  assert.equal(profile.blocked_times[0].day, "Tuesday");
  profile.interests.push("security");
  assert.deepEqual(EMPTY_PROFILE.interests, []);
  assert.deepEqual(toggleValue(["serverless"], "security"), ["serverless", "security"]);
});

test("provenance labels distinguish reservations from recommendations", () => {
  assert.equal(provenanceLabel("existing_reserved"), "Existing reservation");
  assert.equal(provenanceLabel("pathfinder_selected"), "Pathfinder pick");
  assert.equal(provenanceLabel("personal_time"), "Personal time");
});

test("coverage accents are stable by topic across interests and learning goals", () => {
  assert.equal(coverageTopic("Serverless"), "serverless");
  assert.equal(coverageTopic(" security "), "security");
  assert.equal(coverageTopic("OBSERVABILITY"), "observability");
  assert.equal(coverageTopic("databases"), "default");
});

test("Builder ID labels distinguish demo-era access from live attendee access", () => {
  assert.equal(builderIdLabel("not_connected"), "Sign in with AWS Builder ID");
  assert.match(builderIdLabel("connecting"), /Complete AWS Builder ID sign-in/);
  assert.equal(builderIdLabel("registration_required"), "Builder ID connected · re:Invent registration required");
  assert.equal(builderIdLabel("live_aws"), "Live AWS");
  assert.match(safeErrorMessage("auth"), /Builder ID sign-in/);
});

test("Builder ID outcomes explain sign-in and registration without raw transport detail", () => {
  assert.equal(builderIdNotice("not_connected"), null);
  assert.equal(builderIdNotice("connecting"), null);
  assert.equal(builderIdNotice("live_aws"), null);
  assert.match(builderIdNotice("registration_required")?.message ?? "", /signed in.*registered for re:Invent 2026/i);
  assert.match(builderIdNotice("access_unavailable")?.message ?? "", /attendee access/i);
  assert.match(builderIdNotice("sign_in_failed")?.message ?? "", /sign-in.*complete/i);
  for (const state of ["registration_required", "access_unavailable", "sign_in_failed"] as const) {
    assert.doesNotMatch(JSON.stringify(builderIdNotice(state)), /Bearer|access_token|Traceback|private-auth-code/);
  }
});

test("attendee read failures remain distinct after OAuth succeeds", () => {
  assert.match(builderIdNotice("access_unavailable", "authentication_failed")?.message ?? "", /expired|rejected/i);
  assert.match(builderIdNotice("access_unavailable", "authorization_denied")?.message ?? "", /denied/i);
  assert.match(builderIdNotice("access_unavailable", "transport_failure")?.message ?? "", /reach AWS Events/i);
  assert.match(builderIdNotice("access_unavailable", "malformed_response")?.message ?? "", /response/i);
  assert.equal(builderIdNotice("live_aws", "authentication_failed"), null);
});

test("weekly schedule view keeps existing, recommended, and personal items in time order", () => {
  const plan = {
    schedule: { selected_sessions: [
      { hit: { session: { id: "new" } }, event_local_start_at: "2026-11-30T11:00:00-08:00" },
      { hit: { session: { id: "fixed" } }, event_local_start_at: "2026-11-30T09:00:00-08:00" },
    ] },
    session_items: [
      { session: { id: "new" }, source: "pathfinder_selected", is_favorite: true },
      { session: { id: "fixed" }, source: "existing_reserved", is_favorite: false },
    ],
    personal_time_items: [{ event_local_start_at: "2026-11-30T13:00:00-08:00", event_local_end_at: "2026-11-30T14:00:00-08:00", block: { title: "Meeting" } }],
  } as unknown as IntegratedSchedule;
  assert.equal(daysOfWeek(plan)[0], "2026-11-30");
  const entries = scheduleDayEntries(plan, "2026-11-30");
  assert.deepEqual(entries.map((entry) => entry.type === "session" ? entry.source : entry.type), ["existing_reserved", "pathfinder_selected", "personal"]);
  assert.equal(entries[1].type === "session" && entries[1].favorite, true);
});

test("explanation evidence comes from backend fields", () => {
  const why = {
    matched_terms: ["serverless"], matched_interests: ["observability"],
    matched_preferred_services: ["AWS Lambda"], matched_preferred_topics: [],
    matched_desired_levels: ["400"], matched_learning_goals: ["observability"],
    depth_bonus: 3,
  } as SessionExplanation;
  assert.deepEqual(explanationEvidence(why), [
    "Text match: serverless", "observability interest", "Preferred service: AWS Lambda",
    "Level 400 preference", "Learning goal: observability", "Depth bonus: +3",
  ]);
});

test("confirmation requires a reviewed plan ID and demo mode", () => {
  const plan = {
    additions: [{ session_id: "con410", title: "Containers", action: "reserve", reason: "selected" }],
    removals: [], unchanged: [], replacements: [], warnings: [],
    baseline_schedule: { reserved_session_ids: [], favorite_session_ids: [], personal_time: [] },
  } as ScheduleMutationPlan;
  assert.equal(mutationCanConfirm(plan, "1-digest", true), true);
  assert.equal(mutationCanConfirm(plan, null, true), false);
  assert.equal(mutationCanConfirm(plan, "1-digest", false), false);
  assert.equal(mutationCanConfirm(null, "1-digest", true), false);
});

test("partial success and verification mismatch never become generic success", () => {
  const base = {
    reservation_result: { succeeded: ["a"], failed: [{ session_id: "b", code: "sessionFull", message: "Session full" }] },
    cancellation_result: { succeeded: [], failed: [] }, verified_schedule: null,
    verification_failures: [],
  } as MutationExecutionResult;
  assert.deepEqual(mutationOutcome({ ...base, status: "partially_completed" }), { title: "Changes completed with issues", tone: "warning" });
  assert.deepEqual(mutationOutcome({ ...base, status: "verification_failed" }), { title: "Verification issue", tone: "danger" });
});

test("structured error messages avoid raw Python or transport detail", () => {
  assert.match(safeErrorMessage("stale"), /fresh plan/);
  assert.match(safeErrorMessage("network"), /local API/);
  assert.match(safeErrorMessage("access"), /offline demo/);
  assert.doesNotMatch(safeErrorMessage("network"), /Traceback|Exception|Bearer/);
  const base = { message: "upstream traceback detail", data: {}, invoked_service: null, requires_confirmation: false, pending_plan_id: null } as AgentResponse;
  assert.equal(agentErrorMessage({ ...base, status: "error", intent: null }), safeErrorMessage("intent"));
  assert.equal(agentErrorMessage({ ...base, status: "error", intent: "optimize_schedule" }), safeErrorMessage("unschedulable"));
  assert.equal(agentErrorMessage({ ...base, status: "error", intent: "confirm_schedule_mutation", data: { status: "verification_failed" } }), safeErrorMessage("verification"));
});
