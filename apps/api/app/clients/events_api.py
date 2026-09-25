import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.mutations.models import ReservationResult
from app.mutations.normalize import (
    RESERVATION_BATCH_SIZE,
    normalize_reservation_result,
)


class EventsApiError(RuntimeError):
    """A network, HTTP, or response-shape error from AWS Events."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retry_after: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class AwsEventsRestClient:
    """AWS Events transport with explicit write enablement and injected token."""

    def __init__(
        self,
        access_token: str,
        event_id: str = "reinvent2026",
        *,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = "https://api.awsevents.com",
        max_retries: int = 2,
        enable_writes: bool = False,
    ) -> None:
        if not access_token.strip():
            raise ValueError("An AWS Events attendee access token is required")
        if not event_id.strip():
            raise ValueError("An event ID is required")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        self.event_id = event_id
        self.max_retries = max_retries
        self.enable_writes = enable_writes
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(
            base_url=base_url,
            timeout=30.0,
        )
        self._headers = {"Authorization": f"Bearer {access_token}"}

    async def __aenter__(self) -> "AwsEventsRestClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    async def list_sessions(self) -> AsyncIterator[object]:
        """Yield every raw entry; only an absent nextToken ends the walk."""
        token: str | None = None
        seen_tokens: set[str] = set()
        path = f"/v1/events/{self.event_id}/sessions"

        while True:
            params = {"nextToken": token} if token is not None else None
            page = await self._get_page(path, params)
            sessions = page.get("items")
            if not isinstance(sessions, list):
                raise EventsApiError("AWS Events response has no items list")
            for session in sessions:
                yield session

            next_token = page.get("nextToken")
            if next_token is None:
                return
            if not isinstance(next_token, str) or not next_token:
                raise EventsApiError("AWS Events returned an invalid nextToken")
            if next_token in seen_tokens:
                raise EventsApiError("AWS Events repeated a nextToken")
            seen_tokens.add(next_token)
            token = next_token

    async def get_schedule(self) -> dict[str, Any]:
        """Read the raw authenticated GetSchedule response once."""
        return await self._get_page(f"/v1/events/{self.event_id}/schedule", None)

    async def reserve_sessions(self, session_ids: list[str]) -> ReservationResult:
        """Submit one documented 1–10-ID batch; never retry uncertain writes."""
        self._require_writes()
        if not 1 <= len(session_ids) <= RESERVATION_BATCH_SIZE:
            raise ValueError("reservation batch must contain 1 to 10 session IDs")
        if len(session_ids) != len(set(session_ids)) or any(
            not value.strip() for value in session_ids
        ):
            raise ValueError("reservation session IDs must be distinct and nonempty")
        payload = await self._write_request(
            "POST",
            f"/v1/events/{self.event_id}/reservations",
            json_body={"sessionIds": session_ids},
            expected_status=200,
        )
        return normalize_reservation_result(payload, session_ids)

    async def cancel_reservation(self, session_id: str) -> None:
        """Cancel one existing reservation; 404 is a failed operation."""
        self._require_writes()
        if not session_id.strip():
            raise ValueError("session ID is required")
        await self._write_request(
            "DELETE",
            f"/v1/events/{self.event_id}/reservations/{quote(session_id, safe='')}",
            json_body=None,
            expected_status=204,
        )

    def _require_writes(self) -> None:
        if not self.enable_writes:
            raise EventsApiError("AWS Events schedule writes are disabled")

    async def _write_request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, object] | None,
        expected_status: int,
    ) -> dict[str, Any]:
        try:
            response = await self._http_client.request(
                method, path, headers=self._headers, json=json_body
            )
        except httpx.RequestError as error:
            raise EventsApiError(
                "AWS Events write network error; outcome is uncertain"
            ) from error
        if response.status_code != expected_status:
            raise EventsApiError(
                f"AWS Events write returned HTTP {response.status_code}",
                status_code=response.status_code,
                retry_after=response.headers.get("Retry-After"),
            )
        if expected_status == 204:
            return {}
        try:
            payload = response.json()
        except ValueError as error:
            raise EventsApiError("AWS Events write returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise EventsApiError("AWS Events write returned a non-object response")
        return payload

    async def _get_page(
        self, path: str, params: dict[str, str] | None
    ) -> dict[str, Any]:
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._http_client.get(
                    path, params=params, headers=self._headers
                )
            except httpx.RequestError as exc:
                raise EventsApiError("AWS Events network error") from exc

            if (
                response.status_code in {429, 500, 502, 503, 504}
                and attempt < self.max_retries
            ):
                delay = _retry_delay(response.headers.get("Retry-After"), attempt)
                await asyncio.sleep(delay)
                continue
            if response.is_error:
                raise EventsApiError(
                    _safe_http_error(response),
                    status_code=response.status_code,
                )
            try:
                page = response.json()
            except ValueError as exc:
                raise EventsApiError("AWS Events returned invalid JSON") from exc
            if not isinstance(page, dict):
                raise EventsApiError("AWS Events returned a non-object page")
            return page
        raise AssertionError("retry loop exhausted")


def _retry_delay(retry_after: str | None, attempt: int) -> float:
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
    return min(0.5 * 2**attempt, 4.0)


def _safe_http_error(response: httpx.Response) -> str:
    if response.status_code == 403:
        if not response.content:
            return (
                "AWS Events returned HTTP 403 without a body: the edge refused "
                "this address. Slow down and retry later."
            )
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            detail = " ".join(
                value.casefold()
                for key in ("message", "error", "error_description")
                if isinstance(value := payload.get(key), str)
            )
            if any(
                evidence in detail
                for evidence in (
                    "not registered",
                    "registration required",
                    "must register",
                )
            ):
                return (
                    "AWS Events returned HTTP 403: this signed-in attendee "
                    "is not registered for the event. Check registration for "
                    "this Builder ID; signing in again will not help."
                )
            return "AWS Events returned HTTP 403: attendee access was denied"
    return f"AWS Events returned HTTP {response.status_code}"
