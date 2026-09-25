"use client";

import type { AttendeeSchedule, IntegratedSchedule } from "../lib/types";
import { daysOfWeek, scheduleDayEntries } from "../lib/schedule-view";
import { formatClock, formatDay, levelCode, provenanceLabel, sessionCode } from "../lib/view";
import { Icon } from "./Icon";

export function ScheduleBoard({ plan, selectedId, onSelect, verifiedSchedule }: {
  plan: IntegratedSchedule;
  selectedId: string | null;
  onSelect: (id: string) => void;
  verifiedSchedule: AttendeeSchedule | null;
}) {
  return <div className="schedule-grid" aria-label="Optimized weekly schedule">
    {daysOfWeek(plan).map((day) => {
      const entries = scheduleDayEntries(plan, day);
      return <section className="day-column" key={day} aria-label={formatDay(day)}>
        <div className="day-heading"><div><div className="text-[13px] font-bold">{formatDay(day).split(",")[0]}</div><div className="mt-1 text-[11px] text-muted">{formatDay(day).split(",").slice(1).join(",").trim()}</div></div><span className="text-[11px] font-semibold text-muted">{plan.schedule.sessions_per_day[day] ?? 0} sessions</span></div>
        <div className="day-body">
          {entries.length === 0 && <div className="flex flex-1 flex-col items-center justify-center gap-2 py-8 text-center"><Icon name="calendar" size={18} className="text-muted" /><span className="text-[11px] text-muted">Open day for exploring</span></div>}
          {entries.map((entry) => entry.type === "personal" ?
            <div className="session-card personal" key={`personal-${entry.start}`}><div className="technical flex items-center gap-2 text-[11px] font-semibold text-muted"><Icon name="clock" size={13} /> {formatClock(entry.start)}–{formatClock(entry.end)}</div><div className="mt-1.5 session-title">{entry.title}</div><span className="small-badge badge-neutral mt-2">{provenanceLabel("personal_time")}</span></div> :
            <div className={`session-card ${entry.source === "pathfinder_selected" ? "recommended" : ""} ${selectedId === entry.item.hit.session.id ? "selected" : ""}`} key={entry.item.hit.session.id}>
              <div className="technical flex items-center justify-between gap-2 text-[11px] font-semibold text-muted"><span>{formatClock(entry.start)}–{formatClock(entry.item.event_local_end_at)}</span><span>{sessionCode(entry.item.hit.session)}</span></div>
              <h3 className="session-title mt-2">{entry.item.hit.session.title}</h3>
              <div className="session-meta mt-2 flex flex-wrap items-center gap-x-2 gap-y-1">{levelCode(entry.item.hit.session.level) && <span>Level {levelCode(entry.item.hit.session.level)}</span>}{entry.item.hit.session.venue && <span className="inline-flex items-center gap-1"><Icon name="pin" size={10} /> {entry.item.hit.session.venue}</span>}</div>
              <div className="mt-2 flex flex-wrap items-center gap-2"><span className={`small-badge ${entry.source === "existing_reserved" ? "badge-neutral" : "badge-purple"}`}>{provenanceLabel(entry.source)}</span>{entry.favorite && <span className="small-badge badge-neutral">Favorite</span>}{verifiedSchedule?.reserved_session_ids.includes(entry.item.hit.session.id) && entry.source === "pathfinder_selected" && <span className="small-badge badge-success">Verified reserved</span>}</div>
              {entry.source === "pathfinder_selected" && <div className="session-footer"><span className="technical text-[11px] text-muted">FIT <strong className="text-violet">{entry.item.hit.score}</strong></span><button type="button" onClick={() => onSelect(entry.item.hit.session.id)} className="subtle-link" aria-expanded={selectedId === entry.item.hit.session.id}>Why this? →</button></div>}
            </div>
          )}
        </div>
      </section>;
    })}
  </div>;
}
