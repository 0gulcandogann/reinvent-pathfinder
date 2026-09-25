import type { AgentResponse, AttendeeProfile, AttendeeSchedule, BuilderIdStart, BuilderIdStatus, DemoBootstrap, SearchResults } from "./types";
import type { UiErrorKind } from "./view";

export class ApiError extends Error {
  constructor(public status: number, public kind: UiErrorKind, message: string) {
    super(message);
  }
}

async function request<T>(path: string, method: "GET" | "POST", body?: object): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/backend/${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network", "The local API is unavailable.");
  }
  if (!response.ok) {
    let detail: unknown;
    try { detail = (await response.json()).detail; } catch { /* response is not JSON */ }
    const plainDetail = typeof detail === "string" ? detail : "";
    const kind: UiErrorKind = path.startsWith("auth/") ? "auth" :
      response.status === 422 ? "profile" :
      response.status === 409 ? "stale" :
      response.status === 403 || response.status === 503 ||
      (response.status === 404 && path.startsWith("demo/")) ? "access" : "network";
    throw new ApiError(response.status, kind, plainDetail || "The request could not be completed.");
  }
  return response.json() as Promise<T>;
}

export const api = {
  builderIdStatus: () => request<BuilderIdStatus>("auth/builder-id/status", "GET"),
  startBuilderIdLogin: () => request<BuilderIdStart>("auth/builder-id/start", "POST"),
  demoState: () => request<DemoBootstrap>("demo/state", "GET"),
  resetDemo: () => request<DemoBootstrap>("demo/reset", "POST"),
  agentMessage: (message: string, conversationId: string, profile?: AttendeeProfile, currentSchedule?: AttendeeSchedule) =>
    request<AgentResponse>("agent/message", "POST", {
      message, conversation_id: conversationId,
      ...(profile ? { profile } : {}),
      ...(currentSchedule ? { current_schedule: currentSchedule } : {}),
    }),
  recommend: (query: string, profile: AttendeeProfile, filters: Record<string, string[]>) =>
    request<SearchResults>("sessions/recommend", "POST", { query, profile, filters, limit: 40 }),
};
