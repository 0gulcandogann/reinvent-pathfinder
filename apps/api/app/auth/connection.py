"""Process-local Builder ID connection status for the local product UI."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel

from app.auth.events_oauth import login_with_browser
from app.clients.events_api import AwsEventsRestClient, EventsApiError
from app.schedule.normalize import ScheduleNormalizationError, normalize_schedule

BuilderIdState = Literal[
    "not_connected",
    "connecting",
    "registration_required",
    "live_aws",
    "access_unavailable",
    "sign_in_failed",
]
AttendeeAccessFailure = Literal[
    "authentication_failed",
    "authorization_denied",
    "transport_failure",
    "malformed_response",
    "unknown_failure",
]


class BuilderIdStatus(BaseModel):
    state: BuilderIdState
    failure_reason: AttendeeAccessFailure | None = None


class BuilderIdStart(BuilderIdStatus):
    authorization_url: str | None = None


async def _login_from_ui(open_browser: Callable[[str], bool]) -> str:
    """Reuse the PKCE helper while the attendee opens its URL in their browser."""
    return await login_with_browser(browser_open=open_browser)


async def check_attendee_access(access_token: str) -> None:
    """Read attendee access once; the REST client never owns OAuth or writes."""
    async with AwsEventsRestClient(access_token, enable_writes=False) as client:
        normalize_schedule(await client.get_schedule())


class BuilderIdConnection:
    """Keep one local interactive login and its token in this API process."""

    def __init__(
        self,
        *,
        login: Callable[[Callable[[str], bool]], Awaitable[str]] = _login_from_ui,
        check_access: Callable[[str], Awaitable[None]] = check_attendee_access,
    ) -> None:
        self._login = login
        self._check_access = check_access
        self._state: BuilderIdState = "not_connected"
        self._access_token: str | None = None
        self._authorization_url: str | None = None
        self._failure_reason: AttendeeAccessFailure | None = None
        self._task: asyncio.Task[None] | None = None

    def status(self) -> BuilderIdStatus:
        return BuilderIdStatus(state=self._state, failure_reason=self._failure_reason)

    def live_access_token(self) -> str | None:
        """Expose the in-memory token only to the local read-only live bridge."""
        return self._access_token if self._state == "live_aws" else None

    async def recheck(self) -> BuilderIdStatus:
        """Retry an attendee read only after an explicit local user action."""
        if self._access_token is None:
            return self.status()
        self._state = "connecting"
        await self._validate_token(self._access_token)
        return self.status()

    async def start(self) -> BuilderIdStart:
        if self._state in {"connecting", "registration_required", "live_aws"}:
            return BuilderIdStart(
                state=self._state,
                authorization_url=self._authorization_url,
                failure_reason=self._failure_reason,
            )
        self._access_token = None
        self._authorization_url = None
        self._failure_reason = None
        self._state = "connecting"
        url_ready: asyncio.Future[str | None] = (
            asyncio.get_running_loop().create_future()
        )
        self._task = asyncio.create_task(self._connect(url_ready))
        opened_url: str | None = None
        try:
            opened_url = await asyncio.wait_for(url_ready, timeout=10)
        except TimeoutError:
            self._task.cancel()
            self._state = "sign_in_failed"
        return BuilderIdStart(state=self._state, authorization_url=opened_url)

    async def _connect(self, url_ready: asyncio.Future[str | None]) -> None:
        def offer_url(url: str) -> bool:
            self._authorization_url = url
            if not url_ready.done():
                url_ready.set_result(url)
            return True

        try:
            token = await self._login(offer_url)
        except asyncio.CancelledError:
            self._state = "sign_in_failed"
            raise
        except Exception:
            self._state = "sign_in_failed"
            return
        finally:
            if not url_ready.done():
                url_ready.set_result(None)
            self._authorization_url = None
        self._access_token = token
        await self._validate_token(token)

    async def _validate_token(self, token: str) -> None:
        self._failure_reason = None
        try:
            await self._check_access(token)
        except EventsApiError as error:
            if error.status_code == 403 and "not registered" in str(error).casefold():
                self._state = "registration_required"
            else:
                self._state = "access_unavailable"
                self._failure_reason = _classify_access_error(error)
        except ScheduleNormalizationError:
            self._state = "access_unavailable"
            self._failure_reason = "malformed_response"
        except Exception:
            self._state = "access_unavailable"
            self._failure_reason = "unknown_failure"
        else:
            self._state = "live_aws"


def _classify_access_error(error: EventsApiError) -> AttendeeAccessFailure:
    if error.status_code == 401:
        return "authentication_failed"
    if error.status_code == 403:
        return "authorization_denied"
    if error.status_code in {429, 500, 502, 503, 504}:
        return "transport_failure"
    if error.status_code is None:
        if "network error" in str(error).casefold():
            return "transport_failure"
        return "malformed_response"
    return "unknown_failure"
