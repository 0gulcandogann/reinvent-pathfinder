"use client";

import { useState } from "react";
import type { AttendeeProfile } from "../lib/types";
import { depthForLevels, INTEREST_OPTIONS, levelsForDepth, SERVICE_OPTIONS, toggleValue } from "../lib/profile";
import { Icon } from "./Icon";

type Props = {
  profile: AttendeeProfile;
  onChange: (profile: AttendeeProfile) => void;
  onDemo: () => void;
  onOptimize: () => void;
  busy: boolean;
  demoAvailable: boolean;
  demoReady: boolean;
};

export function ProfilePanel({ profile, onChange, onDemo, onOptimize, busy, demoAvailable, demoReady }: Props) {
  const [blockDay, setBlockDay] = useState("Tuesday");
  const [blockStart, setBlockStart] = useState("13:00");
  const [blockEnd, setBlockEnd] = useState("17:00");
  const depth = depthForLevels(profile.desired_levels);
  const tuesdayBlocked = profile.blocked_times.some((block) => block.day.toLowerCase() === "tuesday" && block.start.startsWith("13:00") && block.end.startsWith("17:00"));
  const update = (patch: Partial<AttendeeProfile>) => onChange({ ...profile, ...patch });
  return <section className="panel p-4 md:p-5" aria-labelledby="profile-heading">
    <div className="eyebrow">Your compass</div><h2 id="profile-heading" className="mt-1 text-[19px] font-semibold tracking-tight">What matters to you?</h2>
    <p className="mt-1.5 text-[12px] leading-5 text-muted">Your choices guide the ranking and schedule.</p>
    {demoAvailable && <button type="button" onClick={onDemo} disabled={!demoReady} className="button-secondary mt-3 w-full"><Icon name="spark" size={15} /> {demoReady ? "Use Platform Engineer Demo Profile" : "Loading demo profile…"}</button>}
    <button type="button" onClick={onOptimize} disabled={busy || profile.interests.length === 0} className="button-primary mt-2 w-full min-h-11">{busy ? "Optimizing your week…" : "Optimize my week"} <Icon name="arrow" size={16} /></button>
    <div className="divider my-4" />
    <fieldset>
      <legend className="field-label">Interests <span className="font-normal text-muted">· choose a few</span></legend>
      <div className="flex flex-wrap gap-1.5">{INTEREST_OPTIONS.map((interest) => <button key={interest} type="button" className={`chip ${profile.interests.some((item) => item.toLowerCase() === interest.toLowerCase()) ? "active" : ""}`} aria-pressed={profile.interests.some((item) => item.toLowerCase() === interest.toLowerCase())} onClick={() => update({ interests: toggleValue(profile.interests, interest.toLowerCase()) })}>{interest}</button>)}</div>
    </fieldset>
    <fieldset className="mt-4">
      <legend className="field-label">Technical depth</legend>
      <div className="grid grid-cols-3 gap-2">{(["explore", "intermediate", "deep"] as const).map((value) => <button key={value} type="button" className={`chip capitalize ${depth === value ? "active" : ""}`} aria-pressed={depth === value} onClick={() => update({ desired_levels: levelsForDepth(value), prioritize_depth: value === "deep" })}>{value === "deep" ? "Deep dive" : value}</button>)}</div>
      <p className="mt-2 text-[11px] text-muted">{depth === "explore" ? "Level 100–200" : depth === "intermediate" ? "Level 200–300" : "Level 300–400"}</p>
    </fieldset>
    <fieldset className="mt-4">
      <legend className="field-label">Preferred AWS services</legend>
      <div className="flex flex-wrap gap-1.5">{SERVICE_OPTIONS.map((service) => <button key={service} type="button" className={`chip ${profile.preferred_services.includes(service) ? "active" : ""}`} aria-pressed={profile.preferred_services.includes(service)} onClick={() => update({ preferred_services: toggleValue(profile.preferred_services, service) })}>{service}</button>)}</div>
    </fieldset>
    <div className="inspector-heading mt-5 mb-2">Schedule preferences</div>
    <div className="grid grid-cols-[1fr_auto] items-end gap-3">
      <div><label htmlFor="daily-limit" className="field-label">Max sessions / day</label><select id="daily-limit" className="input" value={profile.max_sessions_per_day ?? ""} onChange={(event) => update({ max_sessions_per_day: event.target.value ? Number(event.target.value) : null })}><option value="">No limit</option>{[2,3,4,5,6,7,8].map((count) => <option value={count} key={count}>{count} sessions</option>)}</select></div>
      <label className="flex min-h-10 items-center gap-2 text-[12px] font-semibold"><input type="checkbox" checked={profile.minimize_venue_changes} onChange={(event) => update({ minimize_venue_changes: event.target.checked })} className="accent-violet" /> Fewer venue changes</label>
    </div>
    <label className="mt-4 flex items-center gap-2 text-[12px] font-semibold"><input type="checkbox" checked={tuesdayBlocked} onChange={(event) => update({ blocked_times: event.target.checked ? [...profile.blocked_times, { day: "Tuesday", start: "13:00:00", end: "17:00:00" }] : profile.blocked_times.filter((block) => block.day.toLowerCase() !== "tuesday") })} className="accent-violet" /> Keep Tuesday 13:00–17:00 free</label>
    <fieldset className="mt-4"><legend className="field-label">Other blocked time</legend><div className="grid grid-cols-[1fr_1fr_1fr] gap-2"><label className="sr-only" htmlFor="block-day">Day</label><select id="block-day" className="input" value={blockDay} onChange={(event) => setBlockDay(event.target.value)}>{["Monday","Tuesday","Wednesday","Thursday","Friday"].map((day) => <option key={day}>{day}</option>)}</select><label className="sr-only" htmlFor="block-start">Start time</label><input id="block-start" type="time" className="input" value={blockStart} onChange={(event) => setBlockStart(event.target.value)} /><label className="sr-only" htmlFor="block-end">End time</label><input id="block-end" type="time" className="input" value={blockEnd} onChange={(event) => setBlockEnd(event.target.value)} /></div><button type="button" className="subtle-link mt-2" disabled={blockEnd <= blockStart} onClick={() => update({ blocked_times: [...profile.blocked_times, { day: blockDay, start: blockStart, end: blockEnd }] })}>+ Add blocked time</button>{profile.blocked_times.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{profile.blocked_times.map((block, index) => <button type="button" className="small-badge badge-neutral" key={`${block.day}-${block.start}-${index}`} aria-label={`Remove ${block.day} ${block.start} to ${block.end} blocked time`} onClick={() => update({ blocked_times: profile.blocked_times.filter((_, itemIndex) => itemIndex !== index) })}>{block.day} {block.start.slice(0,5)}–{block.end.slice(0,5)} ×</button>)}</div>}</fieldset>
    <div className="mt-4"><label htmlFor="learning-goals" className="field-label">Learning goals <span className="font-normal text-muted">· comma separated</span></label><input id="learning-goals" className="input" value={profile.learning_goals.join(", ")} onChange={(event) => update({ learning_goals: event.target.value.split(",").map((value) => value.trim()) })} placeholder="e.g. observability, security" /></div>
  </section>;
}
