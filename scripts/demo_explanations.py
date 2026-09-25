"""Explain a fixture itinerary without AWS credentials."""

import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.catalog.search_service import SessionSearchService  # noqa: E402
from app.catalog.sqlite import SqliteSessionRepository  # noqa: E402
from app.catalog.sync import sync_catalog  # noqa: E402
from app.clients.fake import FakeEventsClient  # noqa: E402
from app.explain.service import explain_schedule  # noqa: E402
from app.models.profile import AttendeeProfile  # noqa: E402
from app.optimizer.solve import optimize_schedule  # noqa: E402

FIXTURE_PATH = ROOT / "data" / "fixtures" / "optimizer_sessions.json"
QUERY = "serverless security observability"


async def main() -> None:
    raw_sessions = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    profile = AttendeeProfile(
        interests=["serverless", "security", "observability"],
        preferred_services=["AWS Lambda"],
        preferred_topics=["Observability"],
        desired_levels=["300", "400"],
        learning_goals=["observability", "security architecture"],
        blocked_times=[{"day": "Tuesday", "start": "13:00", "end": "17:00"}],
        max_sessions_per_day=5,
        minimize_venue_changes=True,
        prioritize_depth=True,
    )
    with TemporaryDirectory() as directory:
        repository = SqliteSessionRepository(Path(directory) / "catalog.sqlite3")
        await sync_catalog(FakeEventsClient(raw_sessions), repository)
        search = SessionSearchService(repository)
        ranked = search.search(QUERY, profile=profile, limit=150)
        fixed = repository.get("plt-m1")
        assert fixed is not None
        schedule = optimize_schedule(ranked.results, profile, fixed_sessions=[fixed])
        explanation = explain_schedule(schedule, profile)

    print("Platform Engineer | explained offline itinerary")
    for item, why in zip(schedule.selected_sessions, explanation.sessions, strict=True):
        session = item.hit.session
        print(
            f"\n{session.start_at:%A %H:%M}-{session.end_at:%H:%M} "
            f"{session.code} {session.title}"
        )
        print(
            f"  Score {why.final_relevance_score} = text {why.text_relevance_score} "
            f"+ preferences {why.preference_score}"
        )
        evidence = []
        if why.matched_terms:
            evidence.append(f"text: {', '.join(why.matched_terms)}")
        if why.matched_interests:
            evidence.append(f"interests: {', '.join(why.matched_interests)}")
        if why.matched_preferred_services:
            evidence.append(f"services: {', '.join(why.matched_preferred_services)}")
        if why.matched_preferred_topics:
            evidence.append(f"topics: {', '.join(why.matched_preferred_topics)}")
        if why.matched_desired_levels:
            evidence.append(f"levels: {', '.join(why.matched_desired_levels)}")
        if why.matched_learning_goals:
            evidence.append(f"goals: {', '.join(why.matched_learning_goals)}")
        if why.depth_bonus:
            evidence.append(f"depth: +{why.depth_bonus}")
        print(f"  Why: {'; '.join(evidence) or 'fixed session'}")
        print(f"  Fit: {why.schedule_fit.message}")
        print(f"  Venue: {why.venue_effect.message}")
        if why.displaced_candidates:
            displaced = ", ".join(
                candidate.session_id for candidate in why.displaced_candidates
            )
            print(f"  Conflicting candidates displaced: {displaced}")

    print("\nBlocked time:")
    for block in profile.blocked_times:
        print(f"  {block.day} {block.start:%H:%M}-{block.end:%H:%M}")

    print("\nImportant rejected sessions:")
    shown_ids = {item.session_id for item in explanation.rejected[:3]}
    shown_ids.update(
        item.session_id
        for item in explanation.rejected
        if item.reason == "blocked_time_conflict"
    )
    for item in explanation.rejected:
        if item.session_id in shown_ids:
            print(f"  {item.code or item.session_id}: {item.message}")

    print("\nSchedule insights:")
    for insight in explanation.insights:
        print(f"  {insight.message}")

    print("\nGoal coverage (relative to considered opportunities):")
    for coverage in explanation.goal_coverage.values():
        print(
            f"  {coverage.label} [{coverage.kind}]: "
            f"{coverage.percentage}% ({coverage.status})"
        )

    metrics = explanation.metrics
    print("\nSummary metrics:")
    print(f"  Selected utility: {metrics.total_selected_utility:g}")
    print(f"  Sessions per day: {metrics.sessions_per_day}")
    print(f"  Venue transitions per day: {metrics.venue_transitions_per_day}")
    print(f"  Total venue transitions: {metrics.total_venue_transitions}")
    print(f"  High-scoring conflicts: {metrics.rejected_high_scoring_conflicts}")
    print(
        f"  Blocked candidates: {metrics.blocked_time_usage.excluded_candidate_count}"
    )
    print(f"  Fixed sessions: {metrics.fixed_session_count}")


if __name__ == "__main__":
    asyncio.run(main())
