"""Fetch and normalize the full AWS Events catalog into data/catalog.json."""

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.auth.events_oauth import OAuthLoginError, login_with_browser  # noqa: E402
from app.catalog.sqlite import SqliteSessionRepository, catalog_db_path  # noqa: E402
from app.catalog.sync import CatalogSyncError, sync_catalog  # noqa: E402
from app.clients.events_api import AwsEventsRestClient, EventsApiError  # noqa: E402


async def run(*, login: bool = False) -> int:
    try:
        token = (
            await login_with_browser()
            if login
            else os.getenv("AWS_EVENTS_ACCESS_TOKEN", "").strip()
        )
        if not token:
            print("Set AWS_EVENTS_ACCESS_TOKEN or run with --login.", file=sys.stderr)
            return 2
        event_id = os.getenv("AWS_EVENTS_EVENT_ID", "reinvent2026")
        async with AwsEventsRestClient(token, event_id=event_id) as client:
            repository = SqliteSessionRepository(catalog_db_path())
            result = await sync_catalog(
                client, repository, ROOT / "data" / "catalog.json"
            )
    except (EventsApiError, OAuthLoginError, CatalogSyncError) as exc:
        print(f"Catalog sync failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Fetched: {result.fetched} | Normalized: {result.normalized} | "
        f"Skipped: {result.skipped} | Errors: {result.errors}"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--login", action="store_true", help="Sign in with AWS Builder ID in a browser"
    )
    raise SystemExit(asyncio.run(run(login=parser.parse_args().login)))
