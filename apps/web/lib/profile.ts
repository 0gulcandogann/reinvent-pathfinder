import type { AttendeeProfile } from "./types";

export type Depth = "explore" | "intermediate" | "deep";

export const INTEREST_OPTIONS = [
  "Serverless", "Security", "Observability", "Containers",
  "Generative AI", "Databases", "Architecture", "Networking",
];

export const SERVICE_OPTIONS = [
  "AWS Lambda", "AWS IAM", "Amazon CloudWatch", "Amazon EKS",
];

export const EMPTY_PROFILE: AttendeeProfile = {
  interests: [], preferred_services: [], preferred_topics: [],
  desired_levels: [], avoided_levels: [], preferred_session_types: [],
  learning_goals: [], blocked_times: [], max_sessions_per_day: 5,
  minimize_venue_changes: false, prioritize_depth: false, diversity_weight: 0,
};

export function levelsForDepth(depth: Depth): string[] {
  return depth === "explore" ? ["100", "200"] :
    depth === "intermediate" ? ["200", "300"] : ["300", "400"];
}

export function depthForLevels(levels: string[]): Depth {
  if (levels.includes("400")) return "deep";
  if (levels.includes("300")) return "intermediate";
  return "explore";
}

export function toggleValue(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

export function profileForRequest(profile: AttendeeProfile): AttendeeProfile {
  return {
    ...profile,
    interests: [...profile.interests],
    preferred_services: [...profile.preferred_services],
    learning_goals: profile.learning_goals.map((goal) => goal.trim()).filter(Boolean),
    blocked_times: profile.blocked_times.map((block) => ({ ...block })),
  };
}
