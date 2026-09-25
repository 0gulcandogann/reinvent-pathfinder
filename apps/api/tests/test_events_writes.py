import asyncio
import json

import httpx
import pytest

from app.clients.events_api import AwsEventsRestClient, EventsApiError
from app.mutations.normalize import ReservationResponseError


def test_live_writes_disabled_by_default_even_with_token() -> None:
    requests = []
    transport = httpx.MockTransport(lambda request: requests.append(request))

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=transport
        ) as http_client:
            client = AwsEventsRestClient("private-token", http_client=http_client)
            with pytest.raises(EventsApiError, match="disabled"):
                await client.reserve_sessions(["a"])
            with pytest.raises(EventsApiError, match="disabled"):
                await client.cancel_reservation("a")

    asyncio.run(run())
    assert requests == []


def test_reserve_uses_exact_contract_and_parses_partial_result() -> None:
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "result": {
                    "successful": ["a", "c"],
                    "failed": [
                        {
                            "sessionId": "b",
                            "code": "sessionFull",
                            "conflictsWith": ["old"],
                        }
                    ],
                }
            },
        )

    async def run():
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=httpx.MockTransport(respond)
        ) as http_client:
            client = AwsEventsRestClient(
                "private-token", http_client=http_client, enable_writes=True
            )
            return await client.reserve_sessions(["a", "b", "c"])

    result = asyncio.run(run())
    assert result.succeeded == ["a", "c"]
    assert result.failed[0].session_id == "b"
    assert result.failed[0].code == "sessionFull"
    assert result.failed[0].conflicts_with == ["old"]
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/v1/events/reinvent2026/reservations"
    assert json.loads(requests[0].content) == {"sessionIds": ["a", "b", "c"]}
    assert requests[0].headers["Authorization"] == "Bearer private-token"


def test_reservation_batch_limit_and_malformed_response() -> None:
    async def run():
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                200, json={"result": {"successful": [], "failed": []}}
            )
        )
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=transport
        ) as http_client:
            client = AwsEventsRestClient(
                "token", http_client=http_client, enable_writes=True
            )
            with pytest.raises(ValueError, match="1 to 10"):
                await client.reserve_sessions([])
            with pytest.raises(ValueError, match="1 to 10"):
                await client.reserve_sessions([str(i) for i in range(11)])
            with pytest.raises(ValueError, match="distinct"):
                await client.reserve_sessions(["a", "a"])
            with pytest.raises(ReservationResponseError, match="requested IDs"):
                await client.reserve_sessions(["a"])

    asyncio.run(run())


def test_unknown_failure_code_is_safe() -> None:
    async def run():
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "result": {
                        "successful": [],
                        "failed": [{"sessionId": "a", "code": "newFutureCode"}],
                    }
                },
            )
        )
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=transport
        ) as http_client:
            client = AwsEventsRestClient(
                "token", http_client=http_client, enable_writes=True
            )
            return await client.reserve_sessions(["a"])

    assert asyncio.run(run()).failed[0].message == "Reservation was refused."


def test_cancel_uses_delete_204_and_404_is_failure() -> None:
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(204 if len(requests) == 1 else 404)

    async def run():
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=httpx.MockTransport(respond)
        ) as http_client:
            client = AwsEventsRestClient(
                "token", http_client=http_client, enable_writes=True
            )
            await client.cancel_reservation("a")
            with pytest.raises(EventsApiError) as error:
                await client.cancel_reservation("a")
            return error.value

    error = asyncio.run(run())
    assert error.status_code == 404
    assert requests[0].method == "DELETE"
    assert requests[0].url.path == "/v1/events/reinvent2026/reservations/a"


def test_write_429_is_not_retried_and_errors_are_redacted(caplog) -> None:
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            429, headers={"Retry-After": "15"}, json={"secret": "private-token"}
        )

    async def run():
        async with httpx.AsyncClient(
            base_url="https://api.awsevents.com", transport=httpx.MockTransport(respond)
        ) as http_client:
            client = AwsEventsRestClient(
                "private-token", http_client=http_client, enable_writes=True
            )
            with pytest.raises(EventsApiError) as error:
                await client.reserve_sessions(["a"])
            return error.value

    error = asyncio.run(run())
    assert len(requests) == 1
    assert error.status_code == 429
    assert error.retry_after == "15"
    assert "private-token" not in str(error)
    assert "private-token" not in caplog.text
