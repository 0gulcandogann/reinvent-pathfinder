import type { IntegratedSchedule, ScheduledSession, SessionExplanation } from "./types";

export type DayEntry =
  | { type: "session"; start: string; item: ScheduledSession; source: "existing_reserved" | "pathfinder_selected"; favorite: boolean }
  | { type: "personal"; start: string; end: string; title: string };

export function daysOfWeek(plan: IntegratedSchedule): string[] {
  const dates = [
    ...plan.schedule.selected_sessions.map((item) => item.event_local_start_at?.slice(0, 10) ?? ""),
    ...plan.personal_time_items.map((item) => item.event_local_start_at.slice(0, 10)),
  ].filter(Boolean).sort();
  if (!dates.length) return [];
  const start = new Date(`${dates[0]}T00:00:00Z`);
  const monday = new Date(start.getTime() - ((start.getUTCDay() + 6) % 7) * 86400000);
  return Array.from({ length: 5 }, (_, index) => new Date(monday.getTime() + index * 86400000).toISOString().slice(0, 10));
}

export function scheduleDayEntries(plan: IntegratedSchedule, day: string): DayEntry[] {
  const byId = new Map(plan.session_items.map((item) => [item.session.id, item]));
  return [
    ...plan.schedule.selected_sessions.filter((item) => item.event_local_start_at?.startsWith(day)).map((item) => ({
      type: "session" as const,
      start: item.event_local_start_at!, item,
      source: byId.get(item.hit.session.id)?.source ?? "pathfinder_selected" as const,
      favorite: byId.get(item.hit.session.id)?.is_favorite ?? false,
    })),
    ...plan.personal_time_items.filter((item) => item.event_local_start_at.startsWith(day)).map((item) => ({
      type: "personal" as const, start: item.event_local_start_at,
      end: item.event_local_end_at, title: item.block.title,
    })),
  ].sort((a, b) => a.start.localeCompare(b.start));
}

export function explanationEvidence(why: SessionExplanation): string[] {
  return [
    ...why.matched_terms.map((term) => `Text match: ${term}`),
    ...why.matched_interests.map((term) => `${term} interest`),
    ...why.matched_preferred_services.map((term) => `Preferred service: ${term}`),
    ...why.matched_preferred_topics.map((term) => `Preferred topic: ${term}`),
    ...why.matched_desired_levels.map((term) => `Level ${term} preference`),
    ...why.matched_learning_goals.map((term) => `Learning goal: ${term}`),
    ...(why.depth_bonus ? [`Depth bonus: +${why.depth_bonus}`] : []),
  ];
}
