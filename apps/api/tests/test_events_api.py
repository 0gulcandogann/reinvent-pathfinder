import asyncio
import json

import httpx
import pytest

from app.clients.events_api import AwsEventsRestClient, EventsApiError


def test_walks_short_pages_until_next_token_is_absent() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        token = request.url.params.get("nextToken")
        pages = {
            None: {"items": [{"sessionId": "1"}], "nextToken": "page-2"},
            "page-2": {"items": [], "nextToken": "page-3"},
            "page-3": {"items": [{"sessionId": "2"}]},
        }
        return httpx.Response(200, json=pages[token])

    async def walk() -> list[object]:
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=httpx.MockTransport(respond)
        ) as http_client:
            async with AwsEventsRestClient("secret", http_client=http_client) as client:
                return [session async for session in client.list_sessions()]

    assert asyncio.run(walk()) == [{"sessionId": "1"}, {"sessionId": "2"}]
    assert [request.url.params.get("nextToken") for request in requests] == [
        None,
        "page-2",
        "page-3",
    ]
    assert all(
        request.headers["Authorization"] == "Bearer secret" for request in requests
    )
    assert requests[0].url.path == "/v1/events/reinvent2026/sessions"


@pytest.mark.parametrize(
    "payload",
    [
        {"notItems": []},
        {"items": "invalid"},
        {"items": [], "nextToken": ""},
    ],
)
def test_rejects_malformed_pages(payload: dict[str, object]) -> None:
    async def walk() -> None:
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(200, json=payload)
        )
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=transport
        ) as http_client:
            client = AwsEventsRestClient("secret", http_client=http_client)
            _ = [session async for session in client.list_sessions()]

    with pytest.raises(EventsApiError):
        asyncio.run(walk())


def test_rejects_repeated_next_token() -> None:
    async def walk() -> None:
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                200, json={"items": [], "nextToken": "again"}
            )
        )
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=transport
        ) as http_client:
            client = AwsEventsRestClient("secret", http_client=http_client)
            _ = [session async for session in client.list_sessions()]

    with pytest.raises(EventsApiError, match="repeated"):
        asyncio.run(walk())


def test_network_error_is_reported() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    async def walk() -> None:
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=httpx.MockTransport(fail)
        ) as http_client:
            client = AwsEventsRestClient("secret", http_client=http_client)
            _ = [session async for session in client.list_sessions()]

    with pytest.raises(EventsApiError, match="network error"):
        asyncio.run(walk())


def test_network_error_does_not_expose_token_or_upstream_exception() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private-token and private detail", request=request)

    async def walk() -> None:
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=httpx.MockTransport(fail)
        ) as http_client:
            client = AwsEventsRestClient("private-token", http_client=http_client)
            _ = [session async for session in client.list_sessions()]

    with pytest.raises(EventsApiError) as error:
        asyncio.run(walk())
    assert "private-token" not in str(error.value)
    assert "private detail" not in str(error.value)


def test_api_error_exposes_status_without_body_or_token() -> None:
    async def walk() -> None:
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(403, text="private server detail")
        )
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=transport
        ) as http_client:
            client = AwsEventsRestClient("secret", http_client=http_client)
            _ = [session async for session in client.list_sessions()]

    with pytest.raises(EventsApiError) as error:
        asyncio.run(walk())
    assert error.value.status_code == 403
    assert "secret" not in str(error.value)
    assert "private server detail" not in str(error.value)


@pytest.mark.parametrize(
    ("response", "expected_hint"),
    [
        (
            httpx.Response(
                403, json={"message": "attendee is not registered for this event"}
            ),
            "not registered",
        ),
        (httpx.Response(403), "edge refused"),
    ],
)
def test_403_explains_safe_distinction(
    response: httpx.Response, expected_hint: str
) -> None:
    async def walk() -> None:
        transport = httpx.MockTransport(lambda _request: response)
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=transport
        ) as http_client:
            client = AwsEventsRestClient("private-token", http_client=http_client)
            _ = [session async for session in client.list_sessions()]

    with pytest.raises(EventsApiError) as error:
        asyncio.run(walk())
    assert error.value.status_code == 403
    assert expected_hint in str(error.value)
    assert "private-token" not in str(error.value)
    assert "attendee is not registered for this event" not in str(error.value)


def test_unrelated_json_403_does_not_claim_missing_registration() -> None:
    async def walk() -> None:
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                403, json={"message": "other private denial"}
            )
        )
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=transport
        ) as http_client:
            client = AwsEventsRestClient("private-token", http_client=http_client)
            _ = [session async for session in client.list_sessions()]

    with pytest.raises(EventsApiError) as error:
        asyncio.run(walk())
    assert "access was denied" in str(error.value)
    assert "not registered" not in str(error.value)
    assert "private-token" not in str(error.value)
    assert "other private denial" not in str(error.value)


def test_registration_word_alone_is_not_proof_of_unregistered_attendee() -> None:
    async def walk() -> None:
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                403, json={"message": "registration service temporarily unavailable"}
            )
        )
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=transport
        ) as http_client:
            client = AwsEventsRestClient("private-token", http_client=http_client)
            _ = [session async for session in client.list_sessions()]

    with pytest.raises(EventsApiError) as error:
        asyncio.run(walk())
    assert "access was denied" in str(error.value)
    assert "not registered" not in str(error.value)


def test_retries_throttling_with_retry_after() -> None:
    calls = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"items": [{"sessionId": "1"}]})

    async def walk() -> list[object]:
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=httpx.MockTransport(respond)
        ) as http_client:
            client = AwsEventsRestClient("secret", http_client=http_client)
            return [session async for session in client.list_sessions()]

    assert asyncio.run(walk()) == [{"sessionId": "1"}]
    assert calls == 2


def test_invalid_json_is_reported() -> None:
    async def walk() -> None:
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(200, text=json.dumps("not an object"))
        )
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=transport
        ) as http_client:
            client = AwsEventsRestClient("secret", http_client=http_client)
            _ = [session async for session in client.list_sessions()]

    with pytest.raises(EventsApiError, match="non-object"):
        asyncio.run(walk())


def test_get_schedule_uses_documented_path_and_injected_bearer_token() -> None:
    requests: list[httpx.Request] = []
    payload = {"schedule": {"reserved": [], "favorites": [], "personalTime": []}}

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload)

    async def read() -> object:
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=httpx.MockTransport(respond)
        ) as http_client:
            client = AwsEventsRestClient("private-token", http_client=http_client)
            return await client.get_schedule()

    assert asyncio.run(read()) == payload
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/v1/events/reinvent2026/schedule"
    assert requests[0].headers["Authorization"] == "Bearer private-token"


def test_get_schedule_api_error_is_typed_and_redacted() -> None:
    async def read() -> object:
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(403, json={"message": "private detail"})
        )
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=transport
        ) as http_client:
            client = AwsEventsRestClient("private-token", http_client=http_client)
            return await client.get_schedule()

    with pytest.raises(EventsApiError) as error:
        asyncio.run(read())
    assert error.value.status_code == 403
    assert "private-token" not in str(error.value)
    assert "private detail" not in str(error.value)
