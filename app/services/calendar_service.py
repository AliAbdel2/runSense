from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from langchain_core.tools import BaseTool, tool



class GoogleCalendarError(RuntimeError):
    def __init__(self, message, status_code=None):
        self.safe_message, self.status_code = message, status_code
        super().__init__(message + (f" (provider status {status_code})" if status_code else ""))


class GoogleCalendarInputError(GoogleCalendarError): pass
class GoogleCalendarConfigurationError(GoogleCalendarError): pass


class GoogleCalendarClient:
    max_attempts = 4
    def __init__(self, access_token, *, calendar_id="primary", base_url="https://www.googleapis.com/calendar/v3", transport=None):
        self._token, self._calendar_id = access_token.strip(), calendar_id.strip() or "primary"
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), transport=transport, timeout=15)
    async def __aenter__(self): return self
    async def __aexit__(self, *_): await self.close()
    async def close(self): await self._client.aclose()
    def _path(self, event_id=None):
        from urllib.parse import quote
        path = f"/calendars/{quote(self._calendar_id, safe='')}/events"
        return path if event_id is None else f"{path}/{quote(event_id, safe='')}"
    async def _request(self, method, path, *, params=None, json=None, retry=True):
        if not self._token: raise GoogleCalendarConfigurationError("GOOGLE_CALENDAR_ACCESS_TOKEN is not configured")
        for attempt in range(self.max_attempts):
            try: response = await self._client.request(method, path, params=params, json=json, headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"})
            except httpx.HTTPError as exc: raise GoogleCalendarError("Google Calendar request failed") from exc
            if retry and (response.status_code == 429 or response.status_code >= 500) and attempt < self.max_attempts - 1:
                try: delay = float(response.headers.get("Retry-After", 0.1 * 2 ** attempt))
                except ValueError: delay = 0.1 * 2 ** attempt
                await asyncio.sleep(min(max(delay, 0), 2)); continue
            if response.status_code >= 400: raise GoogleCalendarError("Google Calendar authentication failed" if response.status_code in (401, 403) else "Google Calendar request failed", response.status_code)
            try: body = response.json()
            except ValueError as exc: raise GoogleCalendarError("Google Calendar returned invalid JSON", response.status_code) from exc
            if not isinstance(body, dict): raise GoogleCalendarError("Google Calendar returned an unexpected response shape", response.status_code)
            return body
        raise GoogleCalendarError("Google Calendar request failed")
    async def get_event(self, event_id):
        if not event_id.strip(): raise GoogleCalendarInputError("event_id cannot be empty")
        return await self._request("GET", self._path(event_id))
    async def insert_event(self, event, *, send_updates):
        if send_updates not in {"all", "none"}: raise GoogleCalendarInputError("send_updates must be all or none")
        return await self._request("POST", self._path(), params={"sendUpdates": send_updates}, json=event, retry=False)
    async def patch_event(self, event_id, event, *, send_updates):
        if send_updates not in {"all", "none"}: raise GoogleCalendarInputError("send_updates must be all or none")
        return await self._request("PATCH", self._path(event_id), params={"sendUpdates": send_updates}, json=event)


GUIDE_STATUSES = {"accepted": "accepted", "declined": "declined", "tentative": "pending", "needsAction": "pending"}


def event_id_for(key: str) -> str:
    if not key.strip(): raise GoogleCalendarInputError("idempotency_key cannot be empty")
    return "runsense" + hashlib.sha256(key.strip().encode()).hexdigest()[:32]


def _email(value):
    if value is None: return None
    value = value.strip().lower()
    if not value or "@" not in value or "." not in value.rsplit("@", 1)[-1] or any(c.isspace() for c in value): raise GoogleCalendarInputError("guide_email is invalid")
    return value


def _owned(event, key):
    private = event.get("extendedProperties", {}).get("private", {})
    return isinstance(private, dict) and private.get("runsense_managed") == "true" and private.get("runsense_idempotency_hash") == hashlib.sha256(key.strip().encode()).hexdigest()


def _payload(**values):
    start, end, zone = values["start"], values["end"], values["time_zone"]
    if start.tzinfo is None or end.tzinfo is None: raise GoogleCalendarInputError("start and end must include a UTC offset")
    if end <= start or (end - start).total_seconds() > 86400: raise GoogleCalendarInputError("Calendar event times are invalid")
    try: ZoneInfo(zone)
    except ZoneInfoNotFoundError as exc: raise GoogleCalendarInputError("time_zone is invalid") from exc
    email = _email(values.get("guide_email")); reminders = list(dict.fromkeys(values.get("reminder_minutes") or [60, 10]))
    if len(reminders) > 5 or any(v < 0 or v > 40320 for v in reminders): raise GoogleCalendarInputError("reminders must contain up to five values from 0 to 40320")
    key = values["idempotency_key"].strip(); body = {"id": event_id_for(key), "summary": values["title"].strip(), "start": {"dateTime": start.astimezone(ZoneInfo(zone)).isoformat(), "timeZone": zone}, "end": {"dateTime": end.astimezone(ZoneInfo(zone)).isoformat(), "timeZone": zone}, "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": v} for v in reminders]}, "extendedProperties": {"private": {"runsense_managed": "true", "runsense_idempotency_hash": hashlib.sha256(key.encode()).hexdigest(), "runsense_session_type": values["session_type"], "runsense_venue_type": values["venue_type"], "runsense_guide_required": str(email is not None).lower()}}}
    if values.get("description"): body["description"] = values["description"].strip()
    if values.get("location"): body["location"] = values["location"].strip()
    if email: body["attendees"], body["status"] = [{"email": email}], "tentative"
    return body


def _normalized(event, created=False, guide_email=None):
    status = None
    for attendee in event.get("attendees", []) if isinstance(event.get("attendees", []), list) else []:
        if isinstance(attendee, dict) and (guide_email is None or attendee.get("email", "").strip().lower() == guide_email): status = GUIDE_STATUSES.get(attendee.get("responseStatus"), "pending"); break
    return {"event_id": event.get("id"), "created": created, "status": event.get("status"), "summary": event.get("summary"), "start": event.get("start"), "end": event.get("end"), "guide_status": status, "html_link": event.get("htmlLink"), "updated": event.get("updated")}


class CalendarService:
    def __init__(self, client: GoogleCalendarClient): self.client = client

    async def create_session(self, *, owner_confirmed: bool, **values):
        if owner_confirmed is not True: raise GoogleCalendarInputError("Creating a Calendar event requires explicit confirmation in the current request")
        body = _payload(**values); key = values["idempotency_key"]; email = _email(values.get("guide_email")); send = "all" if email else "none"
        try:
            response = await self.client.insert_event(body, send_updates=send)
            if response.get("id") != body["id"]: raise GoogleCalendarError("Google Calendar returned an unexpected event ID")
            return _normalized(response, True, email)
        except GoogleCalendarError as exc:
            if exc.status_code not in (409, None) and exc.status_code < 500: raise
            return await self._reconcile(body, key, send, email, allow_insert=exc.status_code != 409)

    async def _reconcile(self, body, key, send, email, *, allow_insert):
        event_id = body["id"]
        for _ in range(2):
            try: existing = await self.client.get_event(event_id)
            except GoogleCalendarError as exc:
                if exc.status_code != 404: raise GoogleCalendarError("Could not reconcile Google Calendar event", exc.status_code) from exc
                await asyncio.sleep(0); continue
            if not _owned(existing, key): raise GoogleCalendarError("Calendar event ID belongs to another event", 409)
            return _normalized(await self.client.patch_event(event_id, body, send_updates=send), False, email)
        if not allow_insert: raise GoogleCalendarError("Could not reconcile Google Calendar event", 404)
        try: return _normalized(await self.client.insert_event(body, send_updates=send), True, email)
        except GoogleCalendarError as exc:
            if exc.status_code == 409: return await self._reconcile(body, key, send, email, allow_insert=False)
            raise GoogleCalendarError("Google Calendar write outcome is uncertain; retry later", exc.status_code) from exc

    async def get_session(self, event_id): return _normalized(await self.client.get_event(event_id))
    async def check_guide(self, event_id, guide_email):
        email = _email(guide_email); event = await self.client.get_event(event_id); status = "not_invited"
        for attendee in event.get("attendees", []) if isinstance(event.get("attendees", []), list) else []:
            if isinstance(attendee, dict) and attendee.get("email", "").strip().lower() == email: status = GUIDE_STATUSES.get(attendee.get("responseStatus"), "pending"); break
        return {"event_id": event.get("id"), "guide_status": status, "session_status": event.get("status"), "updated": event.get("updated")}


class CreateCalendarSessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200); start: datetime; end: datetime; time_zone: str = "Europe/Zurich"
    idempotency_key: str = Field(min_length=5, max_length=200); owner_confirmed: bool = False; description: str | None = None; location: str | None = None
    session_type: str = "run"; venue_type: str = "outdoor"; guide_email: str | None = None; reminder_minutes: list[int] = Field(default_factory=lambda: [60, 10], max_length=5)
    @field_validator("start", "end")
    @classmethod
    def offset(cls, value):
        if value.tzinfo is None or value.utcoffset() is None: raise ValueError("datetime must include a UTC offset")
        return value
    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start: raise ValueError("end must be later than start")
        return self


class EventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=5, max_length=1024)


class GuideInput(EventInput):
    guide_email: str = Field(min_length=3, max_length=320)


def build_calendar_tools(service: CalendarService) -> list[BaseTool]:
    @tool("calendar_create_session", args_schema=CreateCalendarSessionInput)
    async def create(**values):
        """Create or idempotently update one explicitly confirmed training event."""
        return await service.create_session(**values)
    @tool("calendar_get_session", args_schema=EventInput)
    async def get(event_id):
        """Read back one Calendar event."""
        return await service.get_session(event_id)
    @tool("calendar_check_guide", args_schema=GuideInput)
    async def guide(event_id, guide_email):
        """Check the RSVP status for the requested guide attendee."""
        return await service.check_guide(event_id, guide_email)
    return [create, get, guide]
