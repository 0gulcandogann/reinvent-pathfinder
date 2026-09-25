import type { IntegratedSchedule } from "../lib/types";
import { coverageTopic } from "../lib/view";
import { Icon } from "./Icon";

export function InsightsPanel({ plan }: { plan: IntegratedSchedule | null }) {
  if (!plan) return <div className="flex min-h-64 flex-col items-center justify-center border border-dashed border-line p-8 text-center"><Icon name="chart" size={22} className="text-violet" /><h2 className="mt-4 text-lg font-semibold">Insights follow your plan</h2><p className="mt-2 max-w-sm text-sm text-muted">Choose your interests and optimize your week to see goal coverage and schedule patterns.</p></div>;
  const coverage = Object.values(plan.explanation.goal_coverage);
  const metrics = plan.explanation.metrics;
  const figures = [
    { value: metrics.selected_session_count, label: "Sessions selected" },
    { value: metrics.fixed_session_count, label: "Existing reservations" },
    { value: metrics.total_venue_transitions, label: "Venue transitions" },
    { value: metrics.rejected_high_scoring_conflicts, label: "High-scoring conflicts" },
  ];

  return <div className="grid gap-7 lg:grid-cols-[1.18fr_.82fr]">
    <section className="border-t border-line pt-5" aria-labelledby="coverage-heading">
      <div className="eyebrow">Pathfinder coverage</div>
      <h2 id="coverage-heading" className="section-title mt-1">Your learning goals</h2>
      <p className="mt-2 max-w-xl text-[12px] leading-5 text-muted">A relative estimate from the sessions Pathfinder considered. It is not a measure of learning outcomes.</p>
      {coverage.length ? <div className="mt-7 space-y-6">{coverage.map((goal) => <div className={`coverage-topic-${coverageTopic(goal.label)}`} key={`${goal.kind}-${goal.label}`}>
        <div className="mb-2 flex justify-between gap-4"><div><span className="text-[13px] font-semibold capitalize">{goal.label}</span><span className="ml-2 text-[10px] text-muted">{goal.kind === "interest" ? "interest" : "learning goal"}</span></div><span className="coverage-value technical text-[12px] font-semibold">{goal.percentage}%</span></div>
        <div className="coverage-track" role="progressbar" aria-label={`${goal.label} Pathfinder coverage`} aria-valuenow={goal.percentage} aria-valuemin={0} aria-valuemax={100}><div className="coverage-fill" style={{ width: `${goal.percentage}%` }} /></div>
        {goal.status === "no_opportunity" && <p className="mt-1 text-[11px] text-muted">No matching candidate opportunity in this search.</p>}
      </div>)}</div> : <p className="mt-8 border-t border-line py-5 text-[13px] text-muted">Add interests or learning goals to see coverage.</p>}
    </section>
    <div className="space-y-6">
      <section className="border-t border-line pt-5" aria-labelledby="insights-heading"><div className="eyebrow">Schedule health</div><h2 id="insights-heading" className="mt-1 text-[19px] font-semibold tracking-tight">A week with intention</h2><div className="mt-4">{plan.explanation.insights.map((insight, index) => <div className="insight-row text-[12px] leading-5" key={`${insight.code}-${index}`}><Icon name="check" size={14} className="mt-0.5 shrink-0 text-violet" /><span>{insight.message}</span></div>)}</div></section>
      <section className="border-t border-line pt-5" aria-label="Schedule metrics"><div className="eyebrow">The numbers</div><div className="mt-5 grid grid-cols-2 gap-x-7 gap-y-5">{figures.map((figure) => <div className="metric-tile" key={figure.label}><div className="metric-value">{figure.value}</div><div className="metric-label">{figure.label}</div></div>)}</div></section>
    </div>
  </div>;
}
