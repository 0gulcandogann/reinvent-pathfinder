import asyncio
import base64
import hashlib
import re
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

from app.auth.events_oauth import (
    AUTHORIZATION_ENDPOINT,
    CLIENT_ID,
    SCOPES,
    TOKEN_ENDPOINT,
    OAuthLoginError,
    authorization_url,
    exchange_authorization_code,
    generate_pkce_pair,
    generate_state,
    login_with_browser,
    validate_callback,
)


def test_pkce_is_fresh_and_uses_unpadded_s256_base64url() -> None:
    first = generate_pkce_pair()
    second = generate_pkce_pair()
    assert first != second
    assert 43 <= len(first.verifier) <= 128
    assert re.fullmatch(r"[A-Za-z0-9._~-]+", first.verifier)
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(first.verifier.encode("ascii")).digest()
    ).rstrip(b"=")
    assert first.challenge == expected.decode("ascii")
    assert "=" not in first.challenge


def test_state_is_fresh_and_authorization_request_uses_published_values() -> None:
    first_state = generate_state()
    assert first_state != generate_state()
    url = authorization_url("http://127.0.0.1:8484/callback", "challenge", first_state)
    assert urlsplit(url).scheme + "://" + urlsplit(url).netloc + urlsplit(url).path == (
        AUTHORIZATION_ENDPOINT
    )
    params = parse_qs(urlsplit(url).query)
    assert params == {
        "response_type": ["code"],
        "client_id": [CLIENT_ID],
        "redirect_uri": ["http://127.0.0.1:8484/callback"],
        "scope": [SCOPES],
        "identity_provider": ["AWSBuilderID"],
        "code_challenge": ["challenge"],
        "code_challenge_method": ["S256"],
        "state": [first_state],
    }


def test_callback_validates_state_before_returning_code() -> None:
    assert validate_callback(
        {"state": ["expected"], "code": ["private-code"]}, "expected"
    ) == ("private-code")


@pytest.mark.parametrize(
    "params",
    [
        {"state": ["wrong"], "code": ["private-code"]},
        {"code": ["private-code"]},
        {"state": ["expected", "expected"], "code": ["private-code"]},
        {"state": ["expected"], "code": ["one", "two"]},
    ],
)
def test_callback_rejects_invalid_or_ambiguous_values(
    params: dict[str, list[str]],
) -> None:
    with pytest.raises(OAuthLoginError) as error:
        validate_callback(params, "expected")
    assert "private-code" not in str(error.value)


def test_callback_error_is_safe_to_display() -> None:
    with pytest.raises(OAuthLoginError, match="denied or failed") as error:
        validate_callback(
            {
                "state": ["expected"],
                "error": ["access_denied"],
                "error_description": ["private-error-detail"],
            },
            "expected",
        )
    assert "private-error-detail" not in str(error.value)


@pytest.mark.parametrize(
    "response",
    [httpx.Response(400, text="private-token"), httpx.Response(200, json={})],
)
def test_token_exchange_failure_hides_response_secrets(
    response: httpx.Response, capsys
) -> None:
    async def exchange() -> str:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: response)
        ) as client:
            return await exchange_authorization_code(
                "private-code",
                "private-verifier",
                "http://127.0.0.1:8484/callback",
                client,
            )

    with pytest.raises(OAuthLoginError) as error:
        asyncio.run(exchange())
    captured = capsys.readouterr()
    for secret in ("private-code", "private-verifier", "private-token"):
        assert secret not in str(error.value)
        assert secret not in captured.out + captured.err


def test_token_exchange_network_error_is_safe() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private-network-detail", request=request)

    async def exchange() -> str:
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
            return await exchange_authorization_code(
                "private-code",
                "private-verifier",
                "http://127.0.0.1:8484/callback",
                client,
            )

    with pytest.raises(OAuthLoginError) as error:
        asyncio.run(exchange())
    assert "private-network-detail" not in str(error.value)


def test_browser_login_uses_loopback_callback_and_posts_code_without_client_secret(
    capsys,
) -> None:
    requests: list[httpx.Request] = []
    browser_urls: list[str] = []
    browser_responses: list[bytes] = []
    callback_finished = asyncio.Event()

    async def send_callback(redirect_uri: str, state: str) -> None:
        parsed = urlsplit(redirect_uri)
        reader, writer = await asyncio.open_connection("127.0.0.1", parsed.port)
        query = urlencode({"state": state, "code": "private-code"})
        writer.write(
            f"GET /callback?{query} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode("ascii")
        )
        await writer.drain()
        browser_responses.append(await reader.read(4096))
        writer.close()
        await writer.wait_closed()
        callback_finished.set()

    def open_browser(url: str) -> bool:
        browser_urls.append(url)
        params = parse_qs(urlsplit(url).query)
        asyncio.create_task(
            send_callback(params["redirect_uri"][0], params["state"][0])
        )
        return True

    def token_response(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"access_token": "private-access", "refresh_token": "private-refresh"},
        )

    async def login() -> str:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(token_response)
        ) as client:
            token = await login_with_browser(
                browser_open=open_browser,
                http_client=client,
                callback_ports=(0,),
                timeout_seconds=2,
            )
            await asyncio.wait_for(callback_finished.wait(), timeout=2)
            return token

    assert asyncio.run(login()) == "private-access"
    assert len(browser_urls) == 1
    assert browser_responses[0].startswith(b"HTTP/1.1 200 OK")
    assert b"Content-Type: text/html; charset=utf-8" in browser_responses[0]
    assert b"<title>Pathfinder | Authorization received</title>" in browser_responses[0]
    assert b"Return to Pathfinder" in browser_responses[0]
    assert b"private-code" not in browser_responses[0]
    assert requests[0].url == TOKEN_ENDPOINT
    assert requests[0].method == "POST"
    form = parse_qs(requests[0].content.decode("ascii"))
    assert form["grant_type"] == ["authorization_code"]
    assert form["client_id"] == [CLIENT_ID]
    assert form["code"] == ["private-code"]
    assert "client_secret" not in form
    assert (
        form["redirect_uri"]
        == parse_qs(urlsplit(browser_urls[0]).query)["redirect_uri"]
    )
    captured = capsys.readouterr()
    for secret in (
        "private-access",
        "private-refresh",
        "private-code",
        form["code_verifier"][0],
    ):
        assert secret not in captured.out + captured.err


def test_loopback_callback_rejects_wrong_state_without_exchanging_code() -> None:
    token_calls = 0
    browser_responses: list[bytes] = []

    async def send_wrong_state(redirect_uri: str) -> None:
        parsed = urlsplit(redirect_uri)
        reader, writer = await asyncio.open_connection("127.0.0.1", parsed.port)
        writer.write(
            b"GET /callback?state=wrong&code=private-code HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n\r\n"
        )
        await writer.drain()
        browser_responses.append(await reader.read())
        writer.close()
        await writer.wait_closed()

    def open_browser(url: str) -> bool:
        redirect_uri = parse_qs(urlsplit(url).query)["redirect_uri"][0]
        asyncio.create_task(send_wrong_state(redirect_uri))
        return True

    def token_response(_request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        token_calls += 1
        return httpx.Response(200, json={"access_token": "private-access"})

    async def login() -> str:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(token_response)
        ) as client:
            return await login_with_browser(
                browser_open=open_browser,
                http_client=client,
                callback_ports=(0,),
                timeout_seconds=2,
            )

    with pytest.raises(OAuthLoginError, match="state did not match"):
        asyncio.run(login())
    assert token_calls == 0
    assert browser_responses[0].startswith(b"HTTP/1.1 400 Bad Request")
    assert (
        b"<title>Pathfinder | Sign-in could not finish</title>" in browser_responses[0]
    )
    assert b"private-code" not in browser_responses[0]
