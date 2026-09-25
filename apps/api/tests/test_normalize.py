import pytest

from app.catalog.normalize import MalformedSessionError, normalize_session


def test_missing_optional_fields_get_safe_defaults() -> None:
    session = normalize_session({"sessionId": "s-1", "title": "A session"})
    assert session.id == "s-1"
    assert session.title == "A session"
    assert session.code is None
    assert session.abstract is None
    assert session.tracks == []
    assert session.speakers == []
    assert session.start_at is None
    assert session.reservable is False


def test_optional_fields_are_normalized_defensively() -> None:
    session = normalize_session(
        {
            "sessionId": " s-2 ",
            "title": " Technical talk ",
            "abbreviation": "TLC301",
            "type": "Breakout session",
            "tracks": [" Architecture ", None, 7, {"name": "Cloud"}],
            "speakers": [{"name": "Ada"}, "Grace", {}],
            "sessionTime": {"date": "2026-12-01", "time": "09:00", "length": "60"},
            "isReservable": "true",
            "seatAvailability": 4,
        }
    )
    assert session.id == "s-2"
    assert session.title == "Technical talk"
    assert session.code == "TLC301"
    assert session.session_type == "Breakout session"
    assert session.tracks == ["Architecture", "Cloud"]
    assert session.speakers == ["Ada", "Grace"]
    assert session.start_at is not None
    assert session.end_at is not None
    assert (session.end_at - session.start_at).total_seconds() == 3600
    assert session.reservable is False
    assert session.availability is None


def test_published_aws_time_and_availability_fields() -> None:
    session = normalize_session(
        {
            "sessionId": "s-3",
            "title": "Workshop",
            "isReservable": True,
            "seatAvailability": "limited",
            "sessionTime": {
                "date": "2026-12-01",
                "time": "16:00",
                "length": "90",
                "timezone": "America/Los_Angeles",
            },
        }
    )
    assert session.reservable is True
    assert session.availability == "limited"
    assert session.start_at is not None
    assert session.start_at.utcoffset().total_seconds() == -8 * 3600
    assert session.end_at is not None
    assert session.end_at.hour == 17
    assert session.end_at.minute == 30


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"sessionId": "x"},
        {"title": "x"},
        {"sessionId": 1, "title": "x"},
        {"sessionId": "x", "title": "  "},
    ],
)
def test_malformed_sessions_raise(payload: object) -> None:
    with pytest.raises(MalformedSessionError):
        normalize_session(payload)
