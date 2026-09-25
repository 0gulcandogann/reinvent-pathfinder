import type { AgentResponse, AttendeeAccessFailure, AttendeeSchedule, BuilderIdState, MutationExecutionResult, ScheduleMutationPlan, Session } from "./types";

export type UiErrorKind = "profile" | "empty" | "unschedulable" | "intent" | "stale" | "confirmation" | "partial" | "verification" | "access" | "auth" | "network";

export function builderIdLabel(state: BuilderIdState): string {
  const labels: Record<BuilderIdState, string> = {
    not_connected: "Sign in with AWS Builder ID",
    connecting: "Complete AWS Builder ID sign-in in the new tab",
    registration_required: "Builder ID connected · re:Invent registration required",
    live_aws: "Live AWS",
    access_unavailable: "Builder ID connected · attendee access unavailable",
    sign_in_failed: "Sign in with AWS Builder ID",
  };
  return labels[state];
}

export type BuilderIdNotice = { title: string; message: string; tone: "warning" | "danger" };

export function builderIdNotice(state: BuilderIdState, failureReason?: AttendeeAccessFailure | null): BuilderIdNotice | null {
  if (state === "registration_required") return {
    title: "re:Invent registration required",
    message: "You signed in with AWS Builder ID, but this account is not registered for re:Invent 2026. Live attendee access is unavailable. You can continue with demo data.",
    tone: "warning",
  };
  if (state === "access_unavailable") {
    const details: Partial<Record<AttendeeAccessFailure, { title: string; message: string }>> = {
      authentication_failed: { title: "Attendee authentication failed", message: "AWS Builder ID sign-in completed, but AWS Events rejected or expired the attendee token. Sign in again to retry." },
      authorization_denied: { title: "Attendee access denied", message: "AWS Builder ID sign-in completed, but AWS Events denied this attendee read. Pathfinder cannot confirm live access." },
      transport_failure: { title: "AWS Events unavailable", message: "AWS Builder ID sign-in completed, but Pathfinder could not reach AWS Events. Try again later or continue with demo data." },
      malformed_response: { title: "AWS schedule response invalid", message: "AWS Builder ID sign-in completed, but the attendee schedule response could not be safely read. Live access was not confirmed." },
    };
    const detail = failureReason ? details[failureReason] : undefined;
    return { title: detail?.title ?? "Attendee access unavailable", message: detail?.message ?? "AWS Builder ID sign-in completed, but Pathfinder could not verify attendee access. Check your re:Invent access or continue with demo data.", tone: "warning" };
  }
  if (state === "sign_in_failed") return {
    title: "Sign-in did not complete",
    message: "AWS Builder ID sign-in was cancelled, timed out, or could not complete. Please try signing in again.",
    tone: "danger",
  };
  return null;
}

export function coverageTopic(label: string): "serverless" | "security" | "observability" | "default" {
  const topic = label.trim().toLowerCase();
  if (topic === "serverless" || topic === "security" || topic === "observability") return topic;
  return "default";
}

export function provenanceLabel(source: "existing_reserved" | "pathfinder_selected" | "personal_time"): string {
  return source === "existing_reserved" ? "Existing reservation" :
    source === "pathfinder_selected" ? "Pathfinder pick" : "Personal time";
}

export function mutationCanConfirm(plan: ScheduleMutationPlan | null, planId: string | null, demoMode: boolean): boolean {
  return Boolean(demoMode && plan && planId && (plan.additions.length || plan.removals.length));
}

export function mutationOutcome(result: MutationExecutionResult): { title: string; tone: "success" | "warning" | "danger" } {
  if (result.status === "completed") return { title: "Changes verified", tone: "success" };
  if (result.status === "partially_completed") return { title: "Changes completed with issues", tone: "warning" };
  if (result.status === "stale_plan") return { title: "Plan needs a refresh", tone: "warning" };
  if (result.status === "confirmation_required") return { title: "Confirmation required", tone: "warning" };
  return { title: "Verification issue", tone: "danger" };
}

export function safeErrorMessage(kind: UiErrorKind): string {
  const messages: Record<UiErrorKind, string> = {
    profile: "Check your profile choices and try again.",
    empty: "No matching sessions. Try a broader search or fewer filters.",
    unschedulable: "These schedule constraints cannot fit together. Adjust a blocked time or fixed session.",
    intent: "I could not map that message to a supported Pathfinder action. Try a suggested prompt.",
    stale: "Your schedule changed after this plan was created. Build a fresh plan before confirming.",
    confirmation: "Review the proposed changes before confirming.",
    partial: "Some changes did not complete. Check each operation and the verified schedule below.",
    verification: "The final schedule did not match the operation result. Check the verified schedule below.",
    access: "Live attendee access is unavailable for this account. Use the offline demo.",
    auth: "Could not start AWS Builder ID sign-in. Check the local API and try again.",
    network: "The local API is unavailable. Start FastAPI and try again.",
  };
  return messages[kind];
}

export function agentErrorMessage(response: AgentResponse): string | null {
  if (response.data && typeof response.data.status === "string") {
    if (response.data.status === "partially_completed") return safeErrorMessage("partial");
    if (response.data.status === "verification_failed") return safeErrorMessage("verification");
    if (response.data.status === "stale_plan") return safeErrorMessage("stale");
  }
  if (response.status === "ok" || response.status === "confirmation_required") return null;
  if (response.intent === "confirm_schedule_mutation") return safeErrorMessage("confirmation");
  if (response.status === "needs_context") return response.message;
  if (response.intent === "optimize_schedule" || response.intent === "reoptimize_schedule" || response.intent === "set_profile") return safeErrorMessage("unschedulable");
  return safeErrorMessage("intent");
}

export function formatClock(value: string | null): string {
  if (!value) return "Time TBD";
  return value.slice(11, 16);
}

export function formatDay(value: string): string {
  const day = value.slice(0, 10);
  const [year, month, date] = day.split("-").map(Number);
  return new Intl.DateTimeFormat("en-US", { weekday: "long", month: "short", day: "numeric", timeZone: "UTC" }).format(new Date(Date.UTC(year, month - 1, date)));
}

export function levelCode(value: string | null): string | null {
  return value?.match(/\b[1-4]00\b/)?.[0] ?? null;
}

export function sessionCode(session: Session): string {
  return session.code ?? session.id.toUpperCase();
}

export function finalReservedSummary(schedule: AttendeeSchedule | null): string {
  return schedule ? `${schedule.reserved_session_ids.length} reserved session${schedule.reserved_session_ids.length === 1 ? "" : "s"} in the verified schedule` : "Final schedule could not be verified";
}
