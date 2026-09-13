"""Small async client for Google Calendar event operations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Generic, TypeVar
from urllib.parse import quote

import httpx


T = TypeVar("T")


class GoogleCalendarError(RuntimeError):
    """Provider failure whose public message excludes tokens and response bodies."""

    def __init__(self, message: str, status_code: int | None = None):
        self.safe_message = message
        self.status_code = status_code
        suffix = f" (provider status {status_code})" if status_code else ""
        super().__init__(message + suffix)


class GoogleCalendarInputError(GoogleCalendarError):
    """Caller supplied an invalid event value."""


class GoogleCalendarConfigurationError(GoogleCalendarError):
    """Required Calendar credentials or configuration are missing."""


@dataclass(frozen=True)
class CalendarResponse(Generic[T]):
    data: T
    status_code: int


class GoogleCalendarClient:
    """Typed boundary around the Calendar v3 events API."""

    max_attempts = 4

    def __init__(
        self,
        access_token: str,
        *,
        calendar_id: str = "primary",
        base_url: str = "https://www.googleapis.com/calendar/v3",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._access_token = access_token.strip()
        self._calendar_id = calendar_id.strip() or "primary"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            transport=transport,
            timeout=15,
            headers={
                "Accept": "application/json",
                "User-Agent": "RunSense-Calendar-Agent/1.0",
            },
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def close(self):
        await self._client.aclose()

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        if not self._access_token:
            raise GoogleCalendarConfigurationError(
                "GOOGLE_CALENDAR_ACCESS_TOKEN is not configured"
            )
        headers = {"Authorization": f"Bearer {self._access_token}"}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _event_path(self, event_id: str | None = None) -> str:
        calendar = quote(self._calendar_id, safe="")
        path = f"/calendars/{calendar}/events"
        return path if event_id is None else f"{path}/{quote(event_id, safe='')}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        retry_transient: bool = True,
    ) -> CalendarResponse[dict[str, Any]]:
        for attempt in range(self.max_attempts):
            try:
                response = await self._client.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers=self._headers(json_body=json is not None),
                )
            except httpx.HTTPError as exc:
                raise GoogleCalendarError("Google Calendar request failed") from exc

            transient = response.status_code == 429 or response.status_code >= 500
            if retry_transient and transient and attempt < self.max_attempts - 1:
                try:
                    delay = float(response.headers.get("Retry-After", 0.1 * 2**attempt))
                except ValueError:
                    delay = 0.1 * 2**attempt
                await asyncio.sleep(min(max(delay, 0), 2))
                continue

            if response.status_code >= 400:
                message = (
                    "Google Calendar authentication failed"
                    if response.status_code in (401, 403)
                    else "Google Calendar request failed"
                )
                raise GoogleCalendarError(message, response.status_code)
            try:
                body = response.json()
            except ValueError as exc:
                raise GoogleCalendarError(
                    "Google Calendar returned invalid JSON", response.status_code
                ) from exc
            if not isinstance(body, dict):
                raise GoogleCalendarError(
                    "Google Calendar returned an unexpected response shape",
                    response.status_code,
                )
            return CalendarResponse(body, response.status_code)
        raise GoogleCalendarError("Google Calendar request failed")

    async def get_event(self, event_id: str) -> CalendarResponse[dict[str, Any]]:
        if not event_id.strip():
            raise GoogleCalendarInputError("event_id cannot be empty")
        return await self._request("GET", self._event_path(event_id))

    async def insert_event(
        self, event: dict[str, Any], *, send_updates: str
    ) -> CalendarResponse[dict[str, Any]]:
        if send_updates not in {"all", "none"}:
            raise GoogleCalendarInputError("send_updates must be all or none")
        # An insert with a lost response has an uncertain outcome. The service
        # reconciles by deterministic event ID before any retry.
        return await self._request(
            "POST",
            self._event_path(),
            params={"sendUpdates": send_updates},
            json=event,
            retry_transient=False,
        )

    async def patch_event(
        self,
        event_id: str,
        event: dict[str, Any],
        *,
        send_updates: str,
    ) -> CalendarResponse[dict[str, Any]]:
        if send_updates not in {"all", "none"}:
            raise GoogleCalendarInputError("send_updates must be all or none")
        return await self._request(
            "PATCH",
            self._event_path(event_id),
            params={"sendUpdates": send_updates},
            json=event,
        )


# Short aliases mirror the existing application's CalendarClient naming while
# keeping the provider-specific class explicit for the standalone service.
CalendarClient = GoogleCalendarClient
CalendarAPIError = GoogleCalendarError
CalendarInputError = GoogleCalendarInputError
