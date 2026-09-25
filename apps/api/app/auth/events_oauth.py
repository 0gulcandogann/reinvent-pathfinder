"""AWS Events authorization-code login with PKCE and a loopback callback."""

import asyncio
import base64
import hashlib
import secrets
import webbrowser
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

CLIENT_ID = "7vmom55m1qstvq8i71ph127bfq"
AUTHORIZATION_ENDPOINT = "https://oauth.awsevents.com/oauth2/authorize"
TOKEN_ENDPOINT = "https://oauth.awsevents.com/oauth2/token"
SCOPES = "openid email events/access"
CALLBACK_PORTS = range(8484, 8490)


class OAuthLoginError(RuntimeError):
    """A safe-to-display login failure with no upstream secrets."""


@dataclass(frozen=True)
class PkcePair:
    verifier: str
    challenge: str


def generate_pkce_pair() -> PkcePair:
    """Create a fresh 86-character verifier and its unpadded S256 challenge."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PkcePair(verifier=verifier, challenge=challenge)


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def authorization_url(redirect_uri: str, challenge: str, state: str) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "identity_provider": "AWSBuilderID",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    return f"{AUTHORIZATION_ENDPOINT}?{query}"


def validate_callback(params: Mapping[str, list[str]], expected_state: str) -> str:
    states = params.get("state", [])
    if len(states) != 1 or not secrets.compare_digest(states[0], expected_state):
        raise OAuthLoginError("OAuth callback state did not match")
    if "error" in params:
        raise OAuthLoginError("AWS Events sign-in was denied or failed")
    codes = params.get("code", [])
    if len(codes) != 1 or not codes[0]:
        raise OAuthLoginError("OAuth callback did not contain a code")
    return codes[0]


async def exchange_authorization_code(
    code: str,
    verifier: str,
    redirect_uri: str,
    http_client: httpx.AsyncClient,
) -> str:
    """Return only the access token; discard other token response fields."""
    try:
        response = await http_client.post(
            TOKEN_ENDPOINT,
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "redirect_uri": redirect_uri,
                "code": code,
                "code_verifier": verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except httpx.RequestError as exc:
        raise OAuthLoginError("Could not reach the AWS Events token endpoint") from exc
    if response.is_error:
        raise OAuthLoginError(
            f"AWS Events token exchange failed (HTTP {response.status_code})"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise OAuthLoginError("AWS Events token response was invalid JSON") from exc
    if not isinstance(payload, dict):
        raise OAuthLoginError("AWS Events token response was invalid")
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise OAuthLoginError("AWS Events token response had no access token")
    return access_token


async def login_with_browser(
    *,
    browser_open: Callable[[str], bool] = webbrowser.open,
    http_client: httpx.AsyncClient | None = None,
    callback_ports: Iterable[int] = CALLBACK_PORTS,
    timeout_seconds: float = 180,
) -> str:
    """Sign in locally and return an in-memory access token."""
    pkce = generate_pkce_pair()
    state = generate_state()
    loop = asyncio.get_running_loop()
    callback_code: asyncio.Future[str] = loop.create_future()

    async def handle_callback(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        status = "400 Bad Request"
        message = "Sign-in failed. Return to Pathfinder or your terminal."
        try:
            request_headers = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            request_line = request_headers.split(b"\r\n", 1)[0].decode("ascii")
            method, target, _version = request_line.split(" ", 2)
            parsed = urlsplit(target)
            if method != "GET" or parsed.path != "/callback":
                status = "404 Not Found"
                message = "Not found."
            elif callback_code.done():
                status = "409 Conflict"
                message = "Sign-in callback already received."
            else:
                params = parse_qs(parsed.query, keep_blank_values=True)
                try:
                    code = validate_callback(params, state)
                except OAuthLoginError as exc:
                    callback_code.set_exception(exc)
                else:
                    callback_code.set_result(code)
                    status = "200 OK"
                    message = "Sign-in complete. You may close this tab."
        except (
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            TimeoutError,
            ValueError,
            UnicodeError,
        ):
            pass
        finally:
            body = message.encode("utf-8")
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: text/plain; charset=utf-8\r\n"
                f"Content-Length: {len(body)}\r\nCache-Control: no-store\r\n"
                "Connection: close\r\n\r\n".encode("ascii")
                + body
            )
            try:
                await writer.drain()
            except (ConnectionError, OSError):
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except (ConnectionError, OSError):
                    pass

    server: asyncio.AbstractServer | None = None
    for port in callback_ports:
        try:
            server = await asyncio.start_server(
                handle_callback, host="127.0.0.1", port=port, limit=8192
            )
            break
        except OSError:
            continue
    if server is None:
        raise OAuthLoginError("No AWS Events callback port is available (8484-8489)")

    bound_port = server.sockets[0].getsockname()[1]
    redirect_uri = f"http://127.0.0.1:{bound_port}/callback"
    try:
        try:
            opened = browser_open(
                authorization_url(redirect_uri, pkce.challenge, state)
            )
        except Exception as exc:
            raise OAuthLoginError("Could not open the default browser") from exc
        if not opened:
            raise OAuthLoginError("Could not open the default browser")
        try:
            code = await asyncio.wait_for(callback_code, timeout=timeout_seconds)
        except TimeoutError as exc:
            raise OAuthLoginError("Timed out waiting for AWS Events sign-in") from exc
    finally:
        server.close()
        await server.wait_closed()
        if not callback_code.done():
            callback_code.cancel()

    if http_client is not None:
        return await exchange_authorization_code(
            code, pkce.verifier, redirect_uri, http_client
        )
    async with httpx.AsyncClient(timeout=20.0) as owned_client:
        return await exchange_authorization_code(
            code, pkce.verifier, redirect_uri, owned_client
        )
