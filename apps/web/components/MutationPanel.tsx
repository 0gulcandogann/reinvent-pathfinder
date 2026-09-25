import type { MutationExecutionResult, ScheduleMutationPlan } from "../lib/types";
import { finalReservedSummary, mutationCanConfirm, mutationOutcome } from "../lib/view";
import { Icon } from "./Icon";

export function MutationPanel({ plan, planId, result, demoMode, busy, onConfirm, onDismiss }: {
  plan: ScheduleMutationPlan | null;
  planId: string | null;
  result: MutationExecutionResult | null;
  demoMode: boolean;
  busy: boolean;
  onConfirm: () => void;
  onDismiss: () => void;
}) {
  if (!plan && !result) return null;
  if (result) {
    const outcome = mutationOutcome(result);
    return <section className="border-t border-line pt-5" aria-labelledby="mutation-result-title">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1"><div className={`eyebrow badge-${outcome.tone}`}><Icon name="check" size={13} className="mr-1 inline" /> GetSchedule verification</div><span className={`technical text-[10px] uppercase badge-${outcome.tone}`}>{result.status.replaceAll("_", " ")}</span></div>
      <h2 id="mutation-result-title" className="mt-2 text-[23px] font-semibold tracking-tight">{outcome.title}</h2>
      <div className="mt-5 grid gap-5 md:grid-cols-2">
        <div className="verified-card"><h3 className="inspector-heading">API operation result</h3><div className="mt-3 space-y-2 text-[12px]">
          {result.reservation_result.succeeded.map((id) => <div className="flex gap-3" key={`reserve-${id}`}><span className="technical text-violet">+</span><span><strong className="technical font-semibold">{id.toUpperCase()}</strong> reserved</span></div>)}
          {result.cancellation_result.succeeded.map((id) => <div className="flex gap-3" key={`cancel-${id}`}><span className="technical text-[var(--danger)]">−</span><span><strong className="technical font-semibold">{id.toUpperCase()}</strong> cancelled</span></div>)}
          {[...result.reservation_result.failed, ...result.cancellation_result.failed].map((failure) => <div className="flex gap-3 text-[var(--danger)]" key={`failed-${failure.session_id}`}><span className="technical">!</span><span><strong className="technical font-semibold">{failure.session_id.toUpperCase()}</strong> · {failure.message}</span></div>)}
        </div></div>
        <div className="verified-card"><div className="flex items-center gap-2"><Icon name="shield" size={15} className={result.verification_failures.length ? "text-[var(--danger)]" : "text-[var(--success)]"} /><h3 className="inspector-heading">Verified final schedule</h3></div><p className="mt-3 text-[13px] font-semibold">{finalReservedSummary(result.verified_schedule)}</p>{result.verified_schedule && <div className="mt-3 space-y-1 border-t border-line pt-3">{result.verified_schedule.reserved_session_ids.map((id) => <div key={id} className="technical text-[11px] text-secondary">{id.toUpperCase()}</div>)}</div>}<p className="mt-3 text-[10px] text-muted">Read back from GetSchedule after execution.</p></div>
      </div>
      {result.verification_failures.length > 0 && <div role="alert" className="status-box danger mt-4"><strong>Needs attention</strong><ul className="mt-2 list-inside list-disc space-y-1">{result.verification_failures.map((failure, index) => <li key={`${failure.kind}-${index}`}>{failure.message}</li>)}</ul></div>}
      <button type="button" className="button-ghost mt-5" onClick={onDismiss}>Close result</button>
    </section>;
  }
  if (!plan) return null;
  const sections = [
    { title: "KEEP", items: plan.unchanged, tone: "keep", symbol: "=" },
    { title: "REMOVE", items: plan.removals, tone: "remove", symbol: "−" },
    { title: "ADD", items: plan.additions, tone: "add", symbol: "+" },
  ];
  return <section className="border border-line bg-surface p-5 md:p-6" aria-labelledby="mutation-plan-title">
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1"><div className="eyebrow">Plan change</div><span className="technical text-[10px] font-semibold uppercase text-[var(--warning)]">Pending confirmation</span></div>
    <h2 id="mutation-plan-title" className="mt-2 text-[22px] font-semibold tracking-tight">Review before any action.</h2>
    <p className="mt-2 text-[12px] leading-5 text-secondary"><strong className="font-semibold text-ink">No AWS schedule changes have been made yet.</strong> {demoMode ? "Demo execution uses local fixture data." : "Live execution is unavailable in this UI."}</p>
    <div className="mt-5 border-y border-line">{sections.map((section) => <div className="diff-section" key={section.title}><div className={`technical mb-2 text-[10px] font-semibold tracking-wider ${section.tone === "remove" ? "text-[var(--danger)]" : section.tone === "add" ? "text-violet" : "text-muted"}`}>{section.title}</div><div className="space-y-1">{section.items.length ? section.items.map((item) => <div className={`diff-row ${section.tone}`} key={item.session_id}><span className="technical font-semibold" aria-hidden="true">{section.symbol}</span><strong className="technical text-[11px] font-semibold">{item.session_id.toUpperCase()}</strong><span className="title">{item.title ?? "Session"}</span></div>) : <div className="text-[11px] text-muted">None</div>}</div></div>)}</div>
    {plan.warnings.length > 0 && <div className="status-box warning mt-4">{plan.warnings.join(" ")}</div>}
    <div className="mt-5 flex flex-wrap items-center justify-between gap-3"><button type="button" className="button-ghost" disabled={busy} onClick={onDismiss}>Discard plan</button><button type="button" className="button-primary" disabled={busy || !mutationCanConfirm(plan, planId, demoMode)} onClick={onConfirm}><Icon name="shield" size={15} /> {busy ? "Verifying…" : "Confirm demo changes"} <Icon name="arrow" size={14} /></button></div>
    <div className="technical mt-3 text-[10px] text-muted">Plan reference: {planId ?? "unknown"}</div>
  </section>;
}
