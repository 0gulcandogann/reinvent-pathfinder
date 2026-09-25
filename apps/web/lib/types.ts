export type TimeBlock = { day: string; start: string; end: string };

export type AttendeeProfile = {
  interests: string[];
  preferred_services: string[];
  preferred_topics: string[];
  desired_levels: string[];
  avoided_levels: string[];
  preferred_session_types: string[];
  learning_goals: string[];
  blocked_times: TimeBlock[];
  max_sessions_per_day: number | null;
  minimize_venue_changes: boolean;
  prioritize_depth: boolean;
  diversity_weight: number;
};

export type PersonalTime = {
  id: string;
  title: string;
  start_at: string;
  end_at: string;
  description?: string | null;
  location?: string | null;
};

export type AttendeeSchedule = {
  reserved_session_ids: string[];
  favorite_session_ids: string[];
  personal_time: PersonalTime[];
};

export type Session = {
  id: string;
  code: string | null;
  title: string;
  abstract: string | null;
  level: string | null;
  session_type: string | null;
  services: string[];
  topics: string[];
  tracks: string[];
  start_at: string | null;
  end_at: string | null;
  venue: string | null;
};

export type SearchHit = {
  session: Session;
  score: number;
  text_score: number;
  preference_score: number;
  matched_terms: string[];
  matched_preferences: Record<string, string[]>;
  preference_contributions: Record<string, number>;
  penalties: Record<string, number>;
};

export type SearchResults = { total: number; results: SearchHit[] };

export type ScheduledSession = {
  hit: SearchHit;
  fixed: boolean;
  event_local_start_at: string | null;
  event_local_end_at: string | null;
};

export type ScheduleAlternative = {
  hit: SearchHit;
  rejected_reason: string;
  replaces_session_id: string;
};

export type OptimizedSchedule = {
  selected_sessions: ScheduledSession[];
  rejected_sessions: { hit: SearchHit; reason: string; conflicting_with: string[] }[];
  alternatives: Record<string, ScheduleAlternative[]>;
  score: number;
  venue_transitions: number;
  rejected_conflict_count: number;
  sessions_per_day: Record<string, number>;
};

export type SessionExplanation = {
  session_id: string;
  title: string;
  final_relevance_score: number;
  text_relevance_score: number;
  preference_score: number;
  matched_terms: string[];
  matched_interests: string[];
  matched_preferred_services: string[];
  matched_preferred_topics: string[];
  matched_desired_levels: string[];
  matched_learning_goals: string[];
  depth_bonus: number;
  venue_effect: { message: string; penalty_points: number };
  schedule_fit: { message: string };
  displaced_candidates: { session_id: string; title: string; rejection_reason: string }[];
};

export type GoalCoverage = {
  label: string;
  kind: "interest" | "learning_goal";
  percentage: number;
  status: string;
  selected_session_ids: string[];
};

export type ScheduleExplanation = {
  sessions: SessionExplanation[];
  rejected: { session_id: string; title: string; message: string; important: boolean }[];
  insights: { code: string; message: string }[];
  goal_coverage: Record<string, GoalCoverage>;
  metrics: {
    selected_session_count: number;
    sessions_per_day: Record<string, number>;
    total_venue_transitions: number;
    rejected_high_scoring_conflicts: number;
    fixed_session_count: number;
    total_selected_utility: number;
    blocked_time_usage: { configured_blocks: number; excluded_candidate_count: number };
  };
};

export type IntegratedSchedule = {
  schedule: OptimizedSchedule;
  explanation: ScheduleExplanation;
  session_items: { session: Session; source: "existing_reserved" | "pathfinder_selected"; is_favorite: boolean; relevance_score: number }[];
  personal_time_items: { block: PersonalTime; source: "personal_time"; event_local_start_at: string; event_local_end_at: string }[];
  already_reserved_ids: string[];
  proposed_addition_ids: string[];
  favorite_session_ids: string[];
};

export type MutationAction = {
  session_id: string;
  title: string | null;
  action: "reserve" | "cancel" | "keep";
  reason: string;
};

export type ScheduleMutationPlan = {
  baseline_schedule: AttendeeSchedule;
  additions: MutationAction[];
  removals: MutationAction[];
  unchanged: MutationAction[];
  replacements: { old_session_id: string; new_session_id: string }[];
  warnings: string[];
};

export type MutationExecutionResult = {
  status: "confirmation_required" | "stale_plan" | "completed" | "partially_completed" | "verification_failed";
  reservation_result: { succeeded: string[]; failed: { session_id: string; code: string; message: string }[] };
  cancellation_result: { succeeded: string[]; failed: { session_id: string; code: string; message: string }[] };
  verified_schedule: AttendeeSchedule | null;
  verification_failures: { kind: string; session_id: string | null; message: string }[];
};

export type AgentResponse = {
  intent: string | null;
  status: "ok" | "error" | "needs_context" | "confirmation_required";
  message: string;
  data: Record<string, unknown>;
  invoked_service: string | null;
  requires_confirmation: boolean;
  pending_plan_id: string | null;
};

export type DemoBootstrap = {
  mode: "offline_fixture";
  profile: AttendeeProfile;
  existing_schedule: AttendeeSchedule;
  catalog_sessions: number;
};

export type BuilderIdState = "not_connected" | "connecting" | "registration_required" | "live_aws" | "access_unavailable" | "sign_in_failed";
export type AttendeeAccessFailure = "authentication_failed" | "authorization_denied" | "transport_failure" | "malformed_response" | "unknown_failure";
export type BuilderIdStatus = { state: BuilderIdState; failure_reason?: AttendeeAccessFailure | null };
export type BuilderIdStart = BuilderIdStatus & { authorization_url?: string | null };
export type PathfinderMode = "demo" | "live";
export type LiveBootstrap = { mode: "live_aws"; existing_schedule: AttendeeSchedule; catalog_sessions: number };
