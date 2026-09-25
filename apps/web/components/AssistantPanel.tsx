"use client";

import { useEffect, useRef, useState } from "react";
import { Icon } from "./Icon";

export type ChatEntry = { role: "user" | "pathfinder"; text: string; intent?: string | null; status?: string; service?: string | null };

const PROMPTS = [
  { label: "Make Wednesday less busy", message: "Make Wednesday less busy." },
  { label: "Prefer deeper sessions", message: "Give me more advanced sessions." },
  { label: "More security content", message: "I want more security content." },
  { label: "Replace Wednesday 2 PM session", message: "Replace my Wednesday 2 PM session with something more advanced about containers." },
];

function responseLabel(entry: ChatEntry): string | null {
  if (entry.status === "confirmation_required") return "Confirmation required";
  if (entry.intent === "confirm_schedule_mutation") return "Execution result";
  if (entry.intent === "suggest_replacement" || entry.intent === "plan_schedule_mutation") return "Proposal ready";
  if (entry.intent === "reoptimize_schedule" || entry.intent === "optimize_schedule") return "Schedule refined";
  return null;
}

export function AssistantPanel({ entries, busy, onSend, hasPlan }: { entries: ChatEntry[]; busy: boolean; onSend: (message: string) => void; hasPlan: boolean }) {
  const [message, setMessage] = useState("");
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [entries.length]);

  return <section className="border border-line bg-surface" aria-labelledby="assistant-heading">
    <div className="border-b border-line px-5 py-4"><div className="eyebrow">Agent workspace</div><h2 id="assistant-heading" className="mt-1 text-[20px] font-semibold">Ask Pathfinder</h2><p className="mt-1 text-[12px] text-muted">A request becomes a typed action. Pathfinder checks the schedule.</p></div>
    <div ref={logRef} className="chat-scroll space-y-5 px-5 py-5" role="log" aria-live="polite">
      {entries.length === 0 && <div className="border-l-2 border-violet py-2 pl-4"><div className="chat-label">Ready for refinement</div><h3 className="mt-2 text-[15px] font-semibold">Tell Pathfinder what to change.</h3><p className="mt-1 text-[12px] leading-5 text-muted">Start with a command below. Proposed schedule writes appear for review before confirmation.</p></div>}
      {entries.map((entry, index) => <div className={entry.role === "user" ? "chat-user p-3.5" : "chat-agent py-1"} key={index}>
        <div className="chat-label">{entry.role === "user" ? "You" : "Pathfinder"}</div>
        <p className="mt-1.5 text-[13px] leading-5 text-ink">{entry.text}</p>
        {entry.role === "pathfinder" && (responseLabel(entry) || entry.service) && <dl className="chat-detail mt-3">
          {responseLabel(entry) && <><dt>Action</dt><dd className={entry.status === "confirmation_required" ? "text-[var(--warning)]" : entry.intent === "confirm_schedule_mutation" ? "text-[var(--success)]" : "text-violet"}>{responseLabel(entry)}</dd></>}
          {entry.service && <><dt>Source</dt><dd>{entry.service}</dd></>}
        </dl>}
      </div>)}
      {busy && <div role="status" className="technical text-[11px] text-violet">Pathfinder is working…</div>}
    </div>
    <div className="border-t border-line bg-surface p-4 md:p-5"><div className="eyebrow mb-2">Suggested refinements</div><div className="mb-4 flex flex-wrap gap-2">{PROMPTS.map((prompt) => <button type="button" key={prompt.message} className="chip text-left" disabled={busy} onClick={() => onSend(prompt.message)}>{prompt.label} <span aria-hidden="true">↗</span></button>)}</div>
      <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); if (message.trim()) { onSend(message.trim()); setMessage(""); } }}><label htmlFor="assistant-message" className="sr-only">Message Pathfinder</label><input id="assistant-message" className="input min-w-0 flex-1" value={message} onChange={(event) => setMessage(event.target.value)} placeholder={hasPlan ? "Ask about the pending plan…" : "Ask Pathfinder to refine your plan…"} /><button type="submit" className="button-primary !min-h-10" disabled={busy || !message.trim()} aria-label="Send message"><Icon name="send" size={16} /></button></form>
    </div>
  </section>;
}
