"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type { AttendeeProfile, PathfinderMode, SearchResults } from "../lib/types";
import { levelCode, safeErrorMessage, sessionCode } from "../lib/view";
import { SERVICE_OPTIONS } from "../lib/profile";
import { Icon } from "./Icon";

const TOPICS = ["Security", "Serverless", "Observability", "Containers"];
const TYPES = ["Breakout session", "Workshop", "Chalk talk"];

export function DiscoverPanel({ profile, mode }: { profile: AttendeeProfile; mode: PathfinderMode }) {
  const [query, setQuery] = useState("");
  const [level, setLevel] = useState("");
  const [service, setService] = useState("");
  const [topic, setTopic] = useState("");
  const [type, setType] = useState("");
  const [results, setResults] = useState<SearchResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const data = await api.recommend(query, profile, {
          levels: level ? [level] : [], services: service ? [service] : [],
          topics: topic ? [topic] : [], session_types: type ? [type] : [], tracks: [],
        }, mode);
        if (!cancelled) { setResults(data); setError(""); }
      } catch (reason) {
        if (!cancelled) setError(safeErrorMessage(reason instanceof ApiError ? reason.kind : "network"));
      } finally { if (!cancelled) setLoading(false); }
    }, 220);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [query, level, service, topic, type, profile, mode]);

  return <div className="grid gap-7 lg:grid-cols-[245px_minmax(0,1fr)]">
    <aside className="h-fit border-t border-line pt-4">
      <div className="eyebrow">Local catalog / filters</div><h2 className="mt-1 text-[17px] font-semibold">Refine discovery</h2><p className="mt-2 text-[11px] leading-5 text-muted">Searches your local catalog. No per-query AWS requests.</p>
      <div className="divider my-4" />
      <label className="field-label" htmlFor="discover-level">Level</label><select id="discover-level" className="input" value={level} onChange={(event) => setLevel(event.target.value)}><option value="">All levels</option>{["100","200","300","400"].map((value) => <option key={value}>{value}</option>)}</select>
      <label className="field-label mt-4" htmlFor="discover-service">AWS service</label><select id="discover-service" className="input" value={service} onChange={(event) => setService(event.target.value)}><option value="">All services</option>{SERVICE_OPTIONS.map((value) => <option key={value}>{value}</option>)}</select>
      <label className="field-label mt-4" htmlFor="discover-topic">Topic</label><select id="discover-topic" className="input" value={topic} onChange={(event) => setTopic(event.target.value)}><option value="">All topics</option>{TOPICS.map((value) => <option key={value}>{value}</option>)}</select>
      <label className="field-label mt-4" htmlFor="discover-type">Session type</label><select id="discover-type" className="input" value={type} onChange={(event) => setType(event.target.value)}><option value="">All types</option>{TYPES.map((value) => <option key={value}>{value}</option>)}</select>
      <button type="button" className="subtle-link mt-5" onClick={() => { setLevel(""); setService(""); setTopic(""); setType(""); setQuery(""); }}>Clear filters</button>
    </aside>
    <section className="min-w-0">
      <label className="field-label" htmlFor="catalog-search">Search sessions</label><div className="relative"><span className="absolute left-3 top-2.5 text-muted"><Icon name="search" size={17} /></span><input id="catalog-search" className="input !pl-10 !py-3" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Try ‘advanced serverless observability’" /></div>
      <div className="mt-6 flex items-center justify-between"><h2 className="text-[15px] font-semibold">Sessions <span className="technical ml-2 text-[11px] font-normal text-muted">{results ? `${results.total} found` : ""}</span></h2>{loading && <span role="status" className="technical text-[11px] text-violet">Searching…</span>}</div>
      {error && <div role="alert" className="status-box danger mt-4">{error}</div>}
      {!loading && results?.total === 0 && <div className="mt-4 border-y border-line py-10 text-center"><Icon name="search" size={23} className="mx-auto text-muted" /><h3 className="mt-3 font-semibold">No sessions found</h3><p className="mt-1 text-[12px] text-muted">Try a broader search or fewer filters.</p></div>}
      <div className="mt-4">{results?.results.map((hit) => <article key={hit.session.id} className="record-row px-1">
        <div className="flex items-start justify-between gap-4"><div className="min-w-0"><div className="technical text-[10px] font-semibold text-violet">{sessionCode(hit.session)}</div><h3 className="mt-1 text-[15px] font-semibold leading-snug">{hit.session.title}</h3></div><div className="technical shrink-0 text-[11px] text-violet">FIT {hit.score}</div></div>
        {hit.session.abstract && <p className="mt-2 line-clamp-2 text-[12px] leading-5 text-muted">{hit.session.abstract}</p>}
        <div className="technical mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-secondary">{levelCode(hit.session.level) && <span>LEVEL {levelCode(hit.session.level)}</span>}{hit.session.services.slice(0,2).map((value) => <span key={value}>{value}</span>)}{hit.session.topics.slice(0,2).map((value) => <span key={value}>{value}</span>)}</div>
        {Object.values(hit.matched_preferences).flat().length > 0 && <p className="mt-2 text-[11px] text-violet">Matches {Object.values(hit.matched_preferences).flat().slice(0,3).join(" · ")}</p>}
      </article>)}</div>
    </section>
  </div>;
}
