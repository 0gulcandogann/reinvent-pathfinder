"use client";

import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import brandMark from "../app/icon.svg";
import { AssistantPanel, type ChatEntry } from "./AssistantPanel";
import { BuilderIdControl } from "./BuilderIdControl";
import { DiscoverPanel } from "./DiscoverPanel";
import { ExplanationCard } from "./ExplanationCard";
import { Icon } from "./Icon";
import { InsightsPanel } from "./InsightsPanel";
import { MutationPanel } from "./MutationPanel";
import { ProfilePanel } from "./ProfilePanel";
import { ScheduleBoard } from "./ScheduleBoard";
import { api, ApiError } from "../lib/api";
import { canEnterLive, canExecuteDemoMutation, showDemoControls, showLiveAuthControl, themeForMode } from "../lib/mode";
import { EMPTY_PROFILE, profileForRequest } from "../lib/profile";
import type { AgentResponse, AttendeeProfile, AttendeeSchedule, BuilderIdStatus, DemoBootstrap, IntegratedSchedule, MutationExecutionResult, PathfinderMode, ScheduleMutationPlan } from "../lib/types";
import { agentErrorMessage, safeErrorMessage } from "../lib/view";

type Tab = "plan" | "discover" | "insights" | "assistant";
const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";
const EMPTY_SCHEDULE: AttendeeSchedule = { reserved_session_ids: [], favorite_session_ids: [], personal_time: [] };

function isIntegrated(value: Record<string, unknown>): value is IntegratedSchedule & Record<string, unknown> {
  return Boolean(value.schedule && value.explanation && Array.isArray(value.session_items));
}
function isMutationPlan(value: Record<string, unknown>): value is { plan: ScheduleMutationPlan } & Record<string, unknown> {
  return Boolean(value.plan && typeof value.plan === "object");
}
function isExecution(value: Record<string, unknown>): value is MutationExecutionResult & Record<string, unknown> {
  return typeof value.status === "string" && Boolean(value.reservation_result && value.cancellation_result);
}

export function PathfinderApp() {
  const [mode, setMode] = useState<PathfinderMode>("demo");
  const [authStatus, setAuthStatus] = useState<BuilderIdStatus>({ state: "not_connected" });
  const [loginRequest, setLoginRequest] = useState(0);
  const [liveLoading, setLiveLoading] = useState(false);
  const [liveGateOpen, setLiveGateOpen] = useState(false);
  const modeRef = useRef<PathfinderMode>("demo");
  const liveRequested = useRef(false);
  const liveLoadingRef = useRef(false);
  const demoSnapshot = useRef<{ profile: AttendeeProfile; schedule: AttendeeSchedule } | null>(null);
  const latestDemo = useRef<{ profile: AttendeeProfile; schedule: AttendeeSchedule }>({ profile: profileForRequest(EMPTY_PROFILE), schedule: EMPTY_SCHEDULE });
  const [tab, setTab] = useState<Tab>("plan");
  const [bootstrap, setBootstrap] = useState<DemoBootstrap | null>(null);
  const [profile, setProfile] = useState<AttendeeProfile>(profileForRequest(EMPTY_PROFILE));
  const [existingSchedule, setExistingSchedule] = useState<AttendeeSchedule>(EMPTY_SCHEDULE);
  const [plan, setPlan] = useState<IntegratedSchedule | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pendingPlan, setPendingPlan] = useState<ScheduleMutationPlan | null>(null);
  const [pendingPlanId, setPendingPlanId] = useState<string | null>(null);
  const [execution, setExecution] = useState<MutationExecutionResult | null>(null);
  const [chat, setChat] = useState<ChatEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const conversationId = useRef("");

  useEffect(() => {
    conversationId.current = `pathfinder-ui-${crypto.randomUUID()}`;
    if (DEMO_MODE) api.demoState().then((data) => { setBootstrap(data); if (modeRef.current === "demo") setExistingSchedule(data.existing_schedule); }).catch(() => setError("Demo API unavailable. Start FastAPI with PATHFINDER_DEMO_MODE=true."));
  }, []);

  useEffect(() => {
    document.documentElement.dataset.pathfinderMode = themeForMode(mode, liveGateOpen);
  }, [mode, liveGateOpen]);

  useEffect(() => {
    if (mode === "demo") latestDemo.current = { profile, schedule: existingSchedule };
  }, [mode, profile, existingSchedule]);

  async function enterLive(accessState: BuilderIdStatus["state"]) {
    if (liveLoadingRef.current || !liveRequested.current || !canEnterLive(accessState, true)) return;
    liveLoadingRef.current = true;
    setLiveLoading(true);
    try {
      const data = await api.liveBootstrap();
      if (!liveRequested.current) return;
      if (!canEnterLive(accessState, data.mode === "live_aws" && Array.isArray(data.existing_schedule.reserved_session_ids))) {
        throw new ApiError(503, "access", "Live attendee data is incomplete.");
      }
      demoSnapshot.current = latestDemo.current;
      setProfile(profileForRequest(EMPTY_PROFILE));
      setExistingSchedule(data.existing_schedule);
      setPlan(null); setSelectedId(null); setPendingPlan(null); setPendingPlanId(null); setExecution(null); setChat([]);
      conversationId.current = `pathfinder-live-${crypto.randomUUID()}`;
      setNotice("Live AWS attendee data loaded. Schedule writes remain disabled."); setError(""); setTab("plan");
      setLiveGateOpen(false);
      modeRef.current = "live";
      setMode("live");
    } catch (reason) {
      setError(safeErrorMessage(reason instanceof ApiError ? reason.kind : "network"));
      liveRequested.current = false;
    } finally {
      liveLoadingRef.current = false;
      setLiveLoading(false);
    }
  }

  function selectLive() {
    if (mode === "live" || busy || liveLoading) return;
    liveRequested.current = true;
    setLiveGateOpen(true);
    if (authStatus.state === "live_aws") void enterLive(authStatus.state);
    else if (authStatus.state === "registration_required" || authStatus.state === "access_unavailable") setLoginRequest((value) => value + 1);
  }

  function selectDemo() {
    if (busy) return;
    liveRequested.current = false;
    setLiveGateOpen(false);
    if (mode === "demo") { setError(""); return; }
    const previous = demoSnapshot.current;
    setProfile(previous?.profile ?? profileForRequest(EMPTY_PROFILE));
    setExistingSchedule(previous?.schedule ?? bootstrap?.existing_schedule ?? EMPTY_SCHEDULE);
    setPlan(null); setChat([]);
    setPendingPlan(null); setPendingPlanId(null); setExecution(null); setSelectedId(null);
    conversationId.current = `pathfinder-ui-${crypto.randomUUID()}`;
    modeRef.current = "demo";
    setMode("demo"); setTab("plan"); setError("");
    setNotice("Demo data restored. Pending plans were cleared after changing mode.");
  }

  function handleAuthStatus(value: BuilderIdStatus) {
    setAuthStatus(value);
    if (value.state === "live_aws" && liveRequested.current) void enterLive(value.state);
  }

  function absorb(response: AgentResponse) {
    setError(agentErrorMessage(response) ?? "");
    if (isIntegrated(response.data)) { setPlan(response.data); setSelectedId(null); setExecution(null); }
    if (isMutationPlan(response.data) && response.pending_plan_id) {
      setPendingPlan(response.data.plan); setPendingPlanId(response.pending_plan_id); setExecution(null);
      setTimeout(() => document.getElementById("mutation-review")?.scrollIntoView({ behavior: "smooth", block: "center" }), 40);
    }
    if (isExecution(response.data)) {
      setExecution(response.data); setPendingPlan(null); setPendingPlanId(null);
      if (response.data.verified_schedule) setExistingSchedule(response.data.verified_schedule);
    }
    setNotice(response.message);
  }

  async function optimize(nextProfile = profile) {
    if (!nextProfile.interests.length) { setError(safeErrorMessage("profile")); return; }
    setBusy(true); setError(""); setNotice(""); setPendingPlan(null); setPendingPlanId(null);
    try {
      const response = await api.agentMessage(`Build my week around ${nextProfile.interests.join(" ")}.`, conversationId.current, profileForRequest(nextProfile), existingSchedule, mode);
      absorb(response); setTab("plan");
    } catch (reason) { setError(safeErrorMessage(reason instanceof ApiError ? reason.kind : "network")); }
    finally { setBusy(false); }
  }

  async function sendMessage(message: string) {
    if (busy) return;
    setTab("assistant"); setBusy(true); setError("");
    setChat((items) => [...items, { role: "user", text: message }]);
    try {
      const response = await api.agentMessage(message, conversationId.current, undefined, undefined, mode);
      absorb(response);
      setChat((items) => [...items, { role: "pathfinder", text: response.message, intent: response.intent, status: response.status, service: response.invoked_service }]);
    } catch (reason) {
      const text = safeErrorMessage(reason instanceof ApiError ? reason.kind : "network");
      setError(text); setChat((items) => [...items, { role: "pathfinder", text, status: "error" }]);
    } finally { setBusy(false); }
  }

  async function confirmMutation() {
    if (!canExecuteDemoMutation(mode, DEMO_MODE) || !pendingPlan || !pendingPlanId || busy) return;
    setBusy(true); setError("");
    try {
      const response = await api.agentMessage(`Confirm plan ${pendingPlanId}`, conversationId.current);
      absorb(response);
      setChat((items) => [...items, { role: "user", text: "Confirm the reviewed demo plan." }, { role: "pathfinder", text: response.message, intent: response.intent, status: response.status, service: response.invoked_service }]);
    } catch { setError(safeErrorMessage("network")); }
    finally { setBusy(false); }
  }

  async function dismissMutation() {
    if (execution) { setExecution(null); return; }
    if (!pendingPlan || busy) return;
    setBusy(true);
    try {
      const response = await api.agentMessage("Discard plan.", conversationId.current, undefined, undefined, mode);
      if (response.status !== "ok") { setError(response.message); return; }
      setPendingPlan(null); setPendingPlanId(null); setNotice(response.message); setError("");
    } catch { setError(safeErrorMessage("network")); }
    finally { setBusy(false); }
  }

  async function resetDemo() {
    if (!canExecuteDemoMutation(mode, DEMO_MODE) || busy) return;
    setBusy(true);
    try {
      const data = await api.resetDemo();
      setBootstrap(data); setExistingSchedule(data.existing_schedule); setProfile(profileForRequest(EMPTY_PROFILE));
      setPlan(null); setSelectedId(null); setPendingPlan(null); setPendingPlanId(null); setExecution(null); setChat([]);
      conversationId.current = `pathfinder-ui-${crypto.randomUUID()}`;
      setNotice("Demo restored. Choose the Platform Engineer profile to begin again."); setError(""); setTab("plan");
    } catch { setError(safeErrorMessage("network")); }
    finally { setBusy(false); }
  }

  const nav: { id: Tab; label: string; icon: "calendar" | "search" | "chart" | "spark" }[] = [
    { id: "plan", label: "Plan", icon: "calendar" }, { id: "discover", label: "Discover", icon: "search" },
    { id: "insights", label: "Insights", icon: "chart" }, { id: "assistant", label: "Assistant", icon: "spark" },
  ];
  const metrics = plan?.explanation.metrics;
  const goalsCovered = plan ? Object.values(plan.explanation.goal_coverage).filter((goal) => goal.percentage > 0).length : 0;

  return <div className="app-shell">
    <header className="app-header"><div className="app-header-inner"><button type="button" onClick={() => { if (liveGateOpen) selectDemo(); setTab("plan"); }} className="flex shrink-0 items-center gap-2.5 text-left" aria-label="Pathfinder home"><Image src={brandMark} alt="" width={32} height={32} unoptimized priority className="brand-mark" /><span><span className="block text-[15px] font-bold leading-tight tracking-tight">Pathfinder</span><span className="block text-[9px] font-semibold tracking-[.12em] text-muted">RE:INVENT 2026</span></span></button>
      <nav className="app-nav flex items-center gap-1" aria-label="Primary navigation">{nav.map((item) => <button type="button" key={item.id} className={`nav-link ${!liveGateOpen && tab === item.id ? "active" : ""}`} aria-current={!liveGateOpen && tab === item.id ? "page" : undefined} onClick={() => { if (liveGateOpen) selectDemo(); setTab(item.id); }}><Icon name={item.icon} size={16} /> {item.label}</button>)}</nav>
      <div className="ml-auto flex flex-wrap items-center justify-end gap-x-3 gap-y-1"><div className="mode-switch" role="group" aria-label="Data mode"><button type="button" className={mode === "demo" && !liveGateOpen ? "active" : ""} aria-pressed={mode === "demo" && !liveGateOpen} onClick={selectDemo} disabled={busy}>Demo</button><button type="button" className={mode === "live" ? "active" : liveGateOpen ? "requested" : ""} aria-pressed={mode === "live"} onClick={selectLive} disabled={busy || liveLoading}>{liveLoading ? "Connecting…" : "Live"}</button></div>{showDemoControls(mode, liveGateOpen) && DEMO_MODE && <span className="technical text-[10px] font-semibold tracking-wide text-violet">● DEMO DATA</span>}<BuilderIdControl onStatusChange={handleAuthStatus} loginRequest={loginRequest} mode={mode} showControl={showLiveAuthControl(mode, liveGateOpen)} onContinueDemo={selectDemo} />{showDemoControls(mode, liveGateOpen) && DEMO_MODE && <button type="button" className="button-ghost !min-h-8 !border-transparent !px-2 text-[11px]" onClick={resetDemo} disabled={busy}><Icon name="reset" size={12} /> Reset demo</button>}</div>
    </div></header>
    <main className="page-wrap">
      {liveGateOpen && mode === "demo" ? <section className="live-access-gate" aria-labelledby="live-access-heading">
        <div className="eyebrow">LIVE / ACCESS CHECK</div>
        <h1 id="live-access-heading" className="mt-2 text-[31px] font-bold leading-tight tracking-tight md:text-[42px]">Connect to re:Invent 2026.</h1>
        <p className="mt-3 max-w-xl text-[13px] leading-6 text-secondary">Use the AWS Builder ID control in the top bar. Pathfinder opens live attendee data only after AWS Events confirms access and the catalog loads successfully.</p>
        <div className="live-access-steps mt-8 border-y border-line">
          <div><span className="technical text-violet">01</span><span>Sign in with AWS Builder ID</span></div>
          <div><span className="technical text-violet">02</span><span>Verify re:Invent attendee access</span></div>
          <div><span className="technical text-violet">03</span><span>Load your live schedule and catalog</span></div>
        </div>
        <p role="status" className="mt-6 text-[12px] text-secondary">{liveLoading ? "Loading attendee data…" : authStatus.state === "connecting" ? "Complete sign-in in the AWS browser tab…" : authStatus.state === "registration_required" ? "Builder ID connected. re:Invent 2026 registration is required for live access." : authStatus.state === "access_unavailable" ? "Attendee access is unavailable. No live data has been loaded." : "No AWS schedule changes will be made."}</p>
        <button type="button" className="button-secondary mt-6" onClick={selectDemo}>Return to Demo</button>
        <p className="mt-12 border-t border-line pt-4 text-[10px] text-muted">Pathfinder · Live access setup · Schedule writes disabled</p>
      </section> : <>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3"><div><div className="eyebrow">PATHFINDER / {tab.toUpperCase()}</div><h1 className="mt-1 text-[31px] font-bold leading-[1.08] tracking-[-.045em] md:text-[42px]">{tab === "plan" ? "Build a better week." : tab === "discover" ? "Find sessions that fit." : tab === "insights" ? "See the thinking behind your week." : "Refine your week."}</h1><p className="mt-2 max-w-2xl text-[13px] leading-5 text-muted">{tab === "plan" ? "A constraint-aware itinerary built around what you want to learn and what is already on your schedule." : tab === "discover" ? "Search the local catalog and see how each result fits your preferences." : tab === "insights" ? "Coverage and schedule decisions, drawn from your optimized itinerary." : "Turn a request into a typed action and review the resulting schedule."}</p></div>{tab === "plan" && plan && <span className="technical text-[10px] font-semibold text-violet"><Icon name="check" size={12} className="mr-1 inline" /> OPTIMIZED LOCALLY</span>}</div>
      {error && <div role="alert" className="status-box danger mb-5 flex items-start justify-between gap-3"><span>{error}</span><button type="button" onClick={() => setError("")} aria-label="Dismiss error"><Icon name="close" size={15} /></button></div>}
      {notice && !error && <div role="status" className="mb-4 flex items-center gap-2 text-[12px] text-muted"><Icon name="check" size={14} className="text-violet" />{notice}</div>}
      {tab === "plan" && <>
        {plan && <div className="metric-strip mb-5 grid grid-cols-2 md:grid-cols-4"><div className="px-4 py-3 md:px-5"><div className="metric-value">{metrics?.selected_session_count ?? 0}</div><div className="metric-label">Sessions</div></div><div className="px-4 py-3 md:px-5"><div className="metric-value">{plan.schedule.rejected_conflict_count}</div><div className="metric-label">Conflicts resolved</div></div><div className="px-4 py-3 md:px-5"><div className="metric-value">{metrics?.total_venue_transitions ?? 0}</div><div className="metric-label">Venue transitions</div></div><div className="px-4 py-3 md:px-5"><div className="metric-value">{goalsCovered}</div><div className="metric-label">Goals covered</div></div></div>}
        <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_322px]"><div className="min-w-0"><div className="mb-3 flex items-center justify-between"><div><div className="eyebrow">Optimized itinerary</div><h2 className="mt-1 text-[19px] font-semibold tracking-tight">Your week at a glance</h2></div>{plan && <button type="button" onClick={() => setTab("insights")} className="subtle-link">View insights →</button>}</div>
            {plan ? <ScheduleBoard plan={plan} selectedId={selectedId} onSelect={(id) => { setSelectedId(id); setTimeout(() => document.getElementById("why-heading")?.scrollIntoView({ behavior: "smooth", block: "center" }), 40); }} verifiedSchedule={execution?.verified_schedule ?? null} /> : <div className="flex min-h-[360px] flex-col items-center justify-center border border-dashed border-line px-8 text-center"><Icon name="calendar" size={26} className="text-violet" /><h2 className="mt-4 text-[20px] font-semibold tracking-tight">Your week begins here</h2><p className="mt-2 max-w-sm text-[13px] leading-5 text-muted">Choose your interests, set your schedule preferences, then let Pathfinder fit the best sessions together.</p><div className="mt-4 flex flex-wrap justify-center gap-3 text-[11px] text-muted"><span>Preference-aware</span><span>·</span><span>Conflict-free</span><span>·</span><span>Explainable</span></div></div>}
            {plan && <div className="mt-5 flex flex-wrap gap-2"><button type="button" className="button-secondary" disabled={busy} onClick={() => sendMessage("Make Wednesday less busy.")}>Make Wednesday lighter</button><button type="button" className="button-ghost" disabled={busy} onClick={() => { const updated = { ...profile, minimize_venue_changes: true }; setProfile(updated); optimize(updated); }}>Reduce venue changes</button><button type="button" className="button-ghost" disabled={busy} onClick={() => { const updated = { ...profile, desired_levels: ["300", "400"], prioritize_depth: true }; setProfile(updated); optimize(updated); }}>Prefer deeper sessions</button></div>}
          </div><div className="space-y-5">
            {plan && selectedId && <ExplanationCard plan={plan} sessionId={selectedId} onClose={() => setSelectedId(null)} />}
            <ProfilePanel profile={profile} onChange={setProfile} onDemo={() => { if (bootstrap) { setProfile(profileForRequest(bootstrap.profile)); setNotice("Platform Engineer profile loaded. Optimize your week to continue."); setError(""); } }} onOptimize={() => optimize()} busy={busy} demoAvailable={mode === "demo" && DEMO_MODE} demoReady={Boolean(bootstrap)} />
            {plan && !selectedId && <div className="border-l-2 border-violet/50 py-2 pl-4"><div className="eyebrow">Decision trace</div><h3 className="mt-1 text-[15px] font-semibold">Every choice has a reason.</h3><p className="mt-2 text-[12px] leading-5 text-muted">Open “Why this?” on a Pathfinder session to inspect text matches, preferences, schedule fit, and alternatives.</p><button type="button" className="subtle-link mt-3" onClick={() => { const id = plan.session_items.find((item) => item.source === "pathfinder_selected")?.session.id; if (id) setSelectedId(id); }}>Explore a recommendation →</button></div>}
          </div></div>
      </>}
      {tab === "discover" && <DiscoverPanel profile={profile} mode={mode} />}
      {tab === "insights" && <InsightsPanel plan={plan} />}
      {tab === "assistant" && <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_252px]"><AssistantPanel entries={chat} busy={busy} onSend={sendMessage} hasPlan={Boolean(pendingPlan)} /><aside className="h-fit border border-line bg-surface p-4"><div className="eyebrow">Deterministic core</div><h2 className="mt-1 text-[15px] font-semibold">A conversation with guardrails.</h2><dl className="mt-4 space-y-3 text-[11px]"><div className="flex justify-between gap-2 border-b border-line pb-2"><dt className="text-muted">Intent</dt><dd className="text-right text-ink">Typed action</dd></div><div className="flex justify-between gap-2 border-b border-line pb-2"><dt className="text-muted">Ranking</dt><dd className="text-right text-ink">Pathfinder</dd></div><div className="flex justify-between gap-2 border-b border-line pb-2"><dt className="text-muted">Optimization</dt><dd className="text-right text-ink">Deterministic</dd></div><div className="flex justify-between gap-2 pb-1"><dt className="text-muted">Writes</dt><dd className="text-right text-violet">Explicit confirmation</dd></div></dl>{plan && <button type="button" className="button-ghost mt-4 w-full" onClick={() => setTab("plan")}>Back to my week <Icon name="arrow" size={14} /></button>}</aside></div>}
      {(pendingPlan || execution) && <div id="mutation-review" className="mt-6"><MutationPanel plan={pendingPlan} planId={pendingPlanId} result={execution} demoMode={canExecuteDemoMutation(mode, DEMO_MODE)} busy={busy} onConfirm={confirmMutation} onDismiss={dismissMutation} /></div>}
      <footer className="mt-12 border-t border-line pt-4 text-[10px] leading-5 text-muted"><div className="flex flex-wrap items-center justify-between gap-3"><p>Pathfinder · re:Invent 2026 · {mode === "demo" ? "Offline demo" : "Live attendee reads"}</p><p>{mode === "demo" ? "Fixture data · No AWS changes" : "Live writes disabled"}</p></div></footer>
      </>}
    </main>
  </div>;
}
