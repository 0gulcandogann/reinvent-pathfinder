import type { IntegratedSchedule } from "../lib/types";
import { explanationEvidence } from "../lib/schedule-view";
import { sessionCode } from "../lib/view";
import { Icon } from "./Icon";

export function ExplanationCard({ plan, sessionId, onClose }: { plan: IntegratedSchedule; sessionId: string; onClose: () => void }) {
  const why = plan.explanation.sessions.find((item) => item.session_id === sessionId);
  const scheduled = plan.schedule.selected_sessions.find((item) => item.hit.session.id === sessionId);
  if (!why || !scheduled) return null;
  const evidence = explanationEvidence(why);
  const textEvidence = evidence.filter((item) => item.startsWith("Text match:"));
  const preferenceEvidence = evidence.filter((item) => !item.startsWith("Text match:"));
  const alternatives = plan.schedule.alternatives[sessionId] ?? [];

  return <section className="panel p-4 md:p-5" aria-labelledby="why-heading">
    <div className="flex items-start justify-between gap-3">
      <div><div className="eyebrow">Decision detail</div><h2 id="why-heading" className="mt-1 text-[19px] font-semibold tracking-tight">Why this session?</h2></div>
      <button type="button" onClick={onClose} aria-label="Close session explanation" className="button-ghost !min-h-7 !w-7 !p-0"><Icon name="close" size={13} /></button>
    </div>

    <div className="inspector-section">
      <div className="technical text-[11px] font-semibold text-violet">{sessionCode(scheduled.hit.session)}</div>
      <div className="mt-1 text-[15px] font-semibold leading-snug">{why.title}</div>
      <div className="mt-4 flex items-end gap-3"><div><div className="inspector-heading">Fit</div><div className="text-[34px] font-semibold leading-none text-violet">{why.final_relevance_score}</div></div><div className="technical pb-1 text-[10px] leading-5 text-muted"><div>{why.text_relevance_score} text</div><div>{why.preference_score} preferences</div></div></div>
    </div>

    {textEvidence.length > 0 && <div className="inspector-section"><h3 className="inspector-heading">Text relevance</h3><div className="mt-2">{textEvidence.map((item, index) => <div className="inspector-row" key={`${item}-${index}`}><span className="inspector-indicator" />{item}</div>)}</div></div>}
    <div className="inspector-section"><h3 className="inspector-heading">Preference matches</h3><div className="mt-2">{preferenceEvidence.length ? preferenceEvidence.map((item, index) => <div className="inspector-row" key={`${item}-${index}`}><span className="inspector-indicator" />{item}</div>) : <p className="text-[11px] leading-5 text-muted">Selected for its fit within the complete schedule.</p>}</div></div>
    <div className="inspector-section"><h3 className="inspector-heading">Schedule fit</h3><div className="mt-2 space-y-2"><div className="inspector-row"><Icon name="check" size={13} className="mt-0.5 shrink-0 text-violet" /><p>{why.schedule_fit.message}</p></div><div className="inspector-row"><Icon name="pin" size={13} className="mt-0.5 shrink-0 text-violet" /><p>{why.venue_effect.message}</p></div></div></div>
    {why.displaced_candidates.length > 0 && <div className="inspector-section"><h3 className="inspector-heading">Conflicting candidates considered</h3><div className="mt-2 space-y-1 text-[11px] leading-5 text-muted">{why.displaced_candidates.map((item) => <div key={item.session_id}>{item.title} · {item.rejection_reason.replaceAll("_", " ")}</div>)}</div></div>}
    {alternatives.length > 0 && <div className="inspector-section"><h3 className="inspector-heading">Alternatives</h3><div className="mt-2 space-y-2">{alternatives.map((alternative) => <div className="border-l border-line py-1 pl-3" key={alternative.hit.session.id}><div className="text-[11px] font-semibold">{sessionCode(alternative.hit.session)} · {alternative.hit.session.title}</div><div className="mt-1 text-[10px] text-muted">{alternative.rejected_reason.replaceAll("_", " ")} · fit {alternative.hit.score}</div></div>)}</div></div>}
  </section>;
}
