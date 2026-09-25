import json
from pathlib import Path

import pytest

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "fixtures" / "reinvent_sessions.json"
)


@pytest.fixture
def raw_sessions() -> list[object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
