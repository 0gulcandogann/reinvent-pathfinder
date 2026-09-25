import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.clients.fake import FakeEventsClient
from app.schedule.normalize import ScheduleNormalizationError, normalize_schedule

FIXTURE = (
    Path(__file__).resolve().parents[3] / "data" / "fixtures" / "aws_get_schedule.json"
)


def test_get_schedule_response_normalizes_ids_and_utc_personal_time() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    schedule = normalize_schedule(payload)
    assert schedule.reserved_session_ids == ["sec310", "svs320"]
    assert schedule.favorite_session_ids == ["cop330", "fav320", "svst1"]
    block = schedule.personal_time[0]
    assert block.id == "personal-tuesday-afternoon"
    assert block.start_at == datetime(2026, 12, 1, 21, tzinfo=UTC)
    assert block.end_at == datetime(2026, 12, 2, 1, tzinfo=UTC)
    assert block.location == "Expo hall"


def test_missing_optional_personal_time_metadata_is_safe() -> None:
    payload = {
        "schedule": {
            "reserved": ["a", "a"],
            "favorites": ["b", "b"],
            "personalTime": [
                {
                    "personalTimeId": "block-1",
                    "startDateTime": "2026-12-01T21:00:00",
                    "endDateTime": "2026-12-01T22:00:00",
                }
            ],
        }
    }
    schedule = normalize_schedule(payload)
    assert schedule.reserved_session_ids == ["a"]
    assert schedule.favorite_session_ids == ["b"]
    assert schedule.personal_time[0].title == "Personal time"
    assert schedule.personal_time[0].description is None
    assert schedule.personal_time[0].location is None


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"schedule": []},
        {"schedule": {"favorites": [], "personalTime": []}},
        {"schedule": {"reserved": [], "favorites": [], "personalTime": None}},
        {"schedule": {"reserved": [42], "favorites": [], "personalTime": []}},
        {
            "schedule": {
                "reserved": [],
                "favorites": [],
                "personalTime": [{"personalTimeId": "x"}],
            }
        },
        {
            "schedule": {
                "reserved": [],
                "favorites": [],
                "personalTime": [
                    {
                        "personalTimeId": "x",
                        "startDateTime": "2026-12-01T22:00:00",
                        "endDateTime": "2026-12-01T21:00:00",
                    }
                ],
            }
        },
        {
            "schedule": {
                "reserved": [],
                "favorites": [],
                "personalTime": [
                    {
                        "personalTimeId": "x",
                        "startDateTime": "2026-12-01",
                        "endDateTime": "2026-12-01T22:00:00",
                    }
                ],
            }
        },
    ],
)
def test_malformed_schedule_fails_closed(payload: object) -> None:
    with pytest.raises(ScheduleNormalizationError):
        normalize_schedule(payload)


def test_fake_schedule_client_needs_no_credentials_and_returns_a_copy() -> None:
    payload = {"schedule": {"reserved": ["a"], "favorites": [], "personalTime": []}}
    fake = FakeEventsClient(schedule=payload)
    first = asyncio.run(fake.get_schedule())
    first["schedule"]["reserved"].append("changed")
    second = asyncio.run(fake.get_schedule())
    assert second == payload
    assert normalize_schedule(second).reserved_session_ids == ["a"]
