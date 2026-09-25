"""Offline checks for the local Builder ID connection indicator."""

import asyncio
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth.connection import BuilderIdConnection, check_attendee_access
from app.auth.events_oauth import login_with_browser
from app.clients.events_api import AwsEventsRestClient, EventsApiError
from app.main import app
from app.schedule.normalize import ScheduleNormalizationError


def test_builder_id_connection_classifies_registration_403_without_exposing_token() -> (
    None
):
    async def login(open_browser) -> str:
        assert open_browser("https://oauth.awsevents.com/oauth2/authorize?state=test")
        return "private-access-token"

    async def check(token: str) -> None:
        assert token == "private-access-token"
        raise EventsApiError(
            "AWS Events returned HTTP 403: this attendee is not registered",
            status_code=403,
        )

    async def scenario() -> None:
        connection = BuilderIdConnection(login=login, check_access=check)
        assert connection.status().state == "not_connected"
        started = await connection.start()
        assert started.authorization_url.startswith("https://oauth.awsevents.com/")
        await connection._task
        status = connection.status()
        assert status.state == "registration_required"
        assert "private-access-token" not in status.model_dump_json()

    asyncio.run(scenario())


def test_builder_id_connection_marks_read_access_and_rejects_duplicate_start() -> None:
    calls = 0
    gate = asyncio.Event()

    async def login(open_browser) -> str:
        nonlocal calls
        calls += 1
        open_browser("https://oauth.awsevents.com/oauth2/authorize?state=test")
        await gate.wait()
        return "private-access-token"

    async def check(_token: str) -> None:
        return None

    async def scenario() -> None:
        connection = BuilderIdConnection(login=login, check_access=check)
        assert (await connection.start()).authorization_url.startswith(
            "https://oauth.awsevents.com/"
        )
        assert (await connection.start()).state == "connecting"
        gate.set()
        await connection._task
        assert calls == 1
        assert connection.status().state == "live_aws"
        assert (await connection.start()).state == "live_aws"

    asyncio.run(scenario())


def test_registered_attendee_requires_normalized_get_schedule_before_live(
    monkeypatch,
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "schedule": {
                    "reserved": ["unknown-live-session"],
                    "favorites": ["favorite-only"],
                    "personalTime": [],
                }
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=httpx.MockTransport(respond)
        ) as http_client:

            def client_factory(token: str, *, enable_writes: bool):
                assert token == "private-access-token"
                assert enable_writes is False
                return AwsEventsRestClient(
                    token, http_client=http_client, enable_writes=enable_writes
                )

            monkeypatch.setattr(
                "app.auth.connection.AwsEventsRestClient", client_factory
            )

            async def login(open_browser) -> str:
                assert open_browser("https://oauth.awsevents.com/oauth2/authorize")
                return "private-access-token"

            connection = BuilderIdConnection(
                login=login, check_access=check_attendee_access
            )
            assert (await connection.start()).state in {"connecting", "live_aws"}
            await connection._task
            assert connection.status().state == "live_aws"
            assert len(requests) == 1
            assert requests[0].method == "GET"
            assert requests[0].url.path == "/v1/events/reinvent2026/schedule"
            assert "private-access-token" not in connection.status().model_dump_json()

    asyncio.run(scenario())


def test_malformed_get_schedule_cannot_confirm_live_access(monkeypatch) -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com",
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"schedule": {}})
            ),
        ) as http_client:
            monkeypatch.setattr(
                "app.auth.connection.AwsEventsRestClient",
                lambda token, *, enable_writes: AwsEventsRestClient(
                    token, http_client=http_client, enable_writes=enable_writes
                ),
            )
            with pytest.raises(ScheduleNormalizationError):
                await check_attendee_access("private-access-token")

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("error", "expected_reason"),
    [
        (
            EventsApiError("AWS Events returned HTTP 401", status_code=401),
            "authentication_failed",
        ),
        (
            EventsApiError(
                "AWS Events returned HTTP 403: attendee access was denied",
                status_code=403,
            ),
            "authorization_denied",
        ),
        (EventsApiError("AWS Events network error"), "transport_failure"),
        (ScheduleNormalizationError("missing schedule"), "malformed_response"),
    ],
)
def test_live_read_failure_has_safe_specific_reason(error, expected_reason) -> None:
    async def login(_open_browser) -> str:
        return "private-access-token"

    async def check(_token: str) -> None:
        raise error

    async def scenario() -> None:
        connection = BuilderIdConnection(login=login, check_access=check)
        await connection.start()
        await connection._task
        status = connection.status()
        assert status.state == "access_unavailable"
        assert status.failure_reason == expected_reason
        assert "private-access-token" not in status.model_dump_json()

    asyncio.run(scenario())


def test_builder_id_connection_reports_safe_failure_without_token() -> None:
    async def login(_open_browser) -> str:
        raise RuntimeError("private-auth-code")

    async def check(_token: str) -> None:
        raise AssertionError("access check must not run")

    async def scenario() -> None:
        connection = BuilderIdConnection(login=login, check_access=check)
        await connection.start()
        await connection._task
        status = connection.status()
        assert status.state == "sign_in_failed"
        assert "private-auth-code" not in status.model_dump_json()

    asyncio.run(scenario())


def test_ui_start_url_completes_existing_pkce_callback_offline() -> None:
    def token_response(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth2/token"
        assert b"client_secret" not in request.content
        return httpx.Response(200, json={"access_token": "private-access-token"})

    async def login(open_browser) -> str:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(token_response)
        ) as client:
            return await login_with_browser(
                browser_open=open_browser,
                http_client=client,
                callback_ports=[0],
                timeout_seconds=3,
            )

    async def check(token: str) -> None:
        assert token == "private-access-token"
        raise EventsApiError(
            "AWS Events returned HTTP 403: this attendee is not registered",
            status_code=403,
        )

    async def scenario() -> None:
        connection = BuilderIdConnection(login=login, check_access=check)
        started = await connection.start()
        assert started.state == "connecting"
        assert started.authorization_url is not None
        query = parse_qs(urlsplit(started.authorization_url).query)
        callback = query["redirect_uri"][0]
        callback_query = urlencode({"state": query["state"][0], "code": "private-code"})
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(f"{callback}?{callback_query}")
        assert response.status_code == 200
        await connection._task
        assert connection.status().state == "registration_required"
        assert "private-access-token" not in connection.status().model_dump_json()

    asyncio.run(scenario())


def test_ui_pkce_callback_and_attendee_get_schedule_reach_live_offline(
    monkeypatch,
) -> None:
    reads: list[httpx.Request] = []

    def token_response(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth2/token"
        assert b"client_secret" not in request.content
        return httpx.Response(200, json={"access_token": "private-access-token"})

    def schedule_response(request: httpx.Request) -> httpx.Response:
        reads.append(request)
        return httpx.Response(
            200,
            json={
                "schedule": {
                    "reserved": ["live-reservation"],
                    "favorites": ["favorite-only"],
                    "personalTime": [],
                }
            },
        )

    async def scenario() -> None:
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(token_response)) as oauth,
            httpx.AsyncClient(
                base_url="https://api.awsevents.com",
                transport=httpx.MockTransport(schedule_response),
            ) as aws,
        ):
            monkeypatch.setattr(
                "app.auth.connection.AwsEventsRestClient",
                lambda token, *, enable_writes: AwsEventsRestClient(
                    token, http_client=aws, enable_writes=enable_writes
                ),
            )

            async def login(open_browser) -> str:
                return await login_with_browser(
                    browser_open=open_browser,
                    http_client=oauth,
                    callback_ports=[0],
                    timeout_seconds=3,
                )

            connection = BuilderIdConnection(
                login=login, check_access=check_attendee_access
            )
            started = await connection.start()
            assert started.state == "connecting"
            assert connection.status().state == "connecting"
            query = parse_qs(urlsplit(started.authorization_url).query)
            callback = query["redirect_uri"][0]
            async with httpx.AsyncClient(timeout=2) as caller:
                response = await caller.get(
                    f"{callback}?"
                    + urlencode({"state": query["state"][0], "code": "private-code"})
                )
            assert response.status_code == 200
            await connection._task
            assert connection.status().state == "live_aws"
            assert connection.status().failure_reason is None
            assert [(request.method, request.url.path) for request in reads] == [
                ("GET", "/v1/events/reinvent2026/schedule")
            ]
            assert "private-access-token" not in connection.status().model_dump_json()

    asyncio.run(scenario())


def test_auth_status_api_exposes_only_state_and_start_requires_local_host(
    monkeypatch,
) -> None:
    from app.api import auth as auth_api

    async def login(open_browser) -> str:
        open_browser("https://oauth.awsevents.com/oauth2/authorize?state=test")
        return "private-access-token"

    async def check(_token: str) -> None:
        return None

    monkeypatch.setattr(
        auth_api, "connection", BuilderIdConnection(login=login, check_access=check)
    )
    local = TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345)
    )
    assert local.get("/auth/builder-id/status").json() == {"state": "not_connected"}
    started = local.post("/auth/builder-id/start")
    assert started.status_code == 202
    assert started.json()["authorization_url"].startswith(
        "https://oauth.awsevents.com/"
    )
    assert "private-access-token" not in started.text
    remote = TestClient(app, base_url="http://pathfinder.example")
    assert remote.post("/auth/builder-id/start").status_code == 403
