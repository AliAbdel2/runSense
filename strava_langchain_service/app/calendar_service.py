"""Idempotent Google Calendar session creation and guide-status checks."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .calendar_client import (
    GoogleCalendarClient,
    GoogleCalendarConfigurationError,
    GoogleCalendarError,
    GoogleCalendarInputError,
)


GUIDE_STATUSES = {
    "accepted": "accepted",
    "declined": "declined",
    "tentative": "tentative",
    "needsAction": "pending",
}


def event_id_for(idempotency_key: str) -> str:
    """Return a stable Calendar-compatible ID without exposing the caller's key."""
    key = idempotency_key.strip()
    if not key:
        raise GoogleCalendarInputError("idempotency_key cannot be empty")
    return "runsense" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _key_hash(idempotency_key: str) -> str:
    return hashlib.sha256(idempotency_key.strip().encode("utf-8")).hexdigest()


def _owned(event: dict[str, Any], idempotency_key: str) -> bool:
    private = event.get("extendedProperties", {}).get("private", {})
    return (
        isinstance(private, dict)
        and private.get("runsense_managed") == "true"
        and private.get("runsense_idempotency_hash") == _key_hash(idempotency_key)
    )


def _validate_email(value: str | None) -> str | None:
    if value is None:
        return None
    email = value.strip().lower()
    if (
        not email
        or "@" not in email
        or email.startswith("@")
        or email.endswith("@")
        or "." not in email.rsplit("@", 1)[-1]
        or any(char.isspace() for char in email)
    ):
        raise GoogleCalendarInputError("guide_email is invalid")
    return email


def _validated_times(start: datetime, end: datetime, time_zone: str) -> tuple[datetime, datetime]:
    if start.tzinfo is None or start.utcoffset() is None:
        raise GoogleCalendarInputError("start must include a UTC offset")
    if end.tzinfo is None or end.utcoffset() is None:
        raise GoogleCalendarInputError("end must include a UTC offset")
    if end <= start:
        raise GoogleCalendarInputError("end must be later than start")
    if (end - start).total_seconds() > 24 * 60 * 60:
        raise GoogleCalendarInputError("session duration cannot exceed 24 hours")
    try:
        zone = ZoneInfo(time_zone)
    except ZoneInfoNotFoundError as exc:
        raise GoogleCalendarInputError("time_zone is invalid") from exc
    return start.astimezone(zone), end.astimezone(zone)


def _event_payload(
    *,
    title: str,
    start: datetime,
    end: datetime,
    time_zone: str,
    idempotency_key: str,
    description: str | None,
    location: str | None,
    session_type: str,
    venue_type: str,
    guide_email: str | None,
    reminder_minutes: list[int],
) -> dict[str, Any]:
    start, end = _validated_times(start, end, time_zone)
    guide_email = _validate_email(guide_email)
    event_id = event_id_for(idempotency_key)
    if not title.strip():
        raise GoogleCalendarInputError("title cannot be empty")
    reminders = list(dict.fromkeys(reminder_minutes))
    if len(reminders) > 5 or any(value < 0 or value > 40_320 for value in reminders):
        raise GoogleCalendarInputError("reminders must contain up to five values from 0 to 40320")

    payload: dict[str, Any] = {
        "id": event_id,
        "summary": title.strip(),
        "start": {"dateTime": start.isoformat(), "timeZone": time_zone},
        "end": {"dateTime": end.isoformat(), "timeZone": time_zone},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": value} for value in reminders
            ],
        },
        "extendedProperties": {
            "private": {
                "runsense_managed": "true",
                "runsense_idempotency_hash": _key_hash(idempotency_key),
                "runsense_session_type": session_type,
                "runsense_venue_type": venue_type,
                "runsense_guide_required": str(guide_email is not None).lower(),
            }
        },
    }
    if description:
        payload["description"] = description.strip()
    if location:
        payload["location"] = location.strip()
    if guide_email:
        payload["attendees"] = [{"email": guide_email}]
        # An invitation is not an acceptance. A guide-dependent session stays
        # tentative until calendar_check_guide reports accepted.
        payload["status"] = "tentative"
    return payload


def _normalized(
    event: dict[str, Any], *, created: bool, guide_email: str | None = None
) -> dict[str, Any]:
    attendees = event.get("attendees", [])
    guide_status = None
    if isinstance(attendees, list) and attendees:
        expected = guide_email.strip().lower() if guide_email else None
        for attendee in attendees:
            if not isinstance(attendee, dict):
                continue
            if expected is None or str(attendee.get("email", "")).strip().lower() == expected:
                guide_status = GUIDE_STATUSES.get(attendee.get("responseStatus"), "pending")
                break
    return {
        "event_id": event.get("id"),
        "created": created,
        "status": event.get("status"),
        "summary": event.get("summary"),
        "start": event.get("start"),
        "end": event.get("end"),
        "guide_status": guide_status,
        "html_link": event.get("htmlLink"),
        "updated": event.get("updated"),
    }


class CalendarService:
    def __init__(self, client: GoogleCalendarClient):
        self.client = client

    async def create_session(
        self,
        *,
        title: str,
        start: datetime,
        end: datetime,
        time_zone: str,
        idempotency_key: str,
        owner_confirmed: bool,
        description: str | None = None,
        location: str | None = None,
        session_type: str = "run",
        venue_type: str = "outdoor",
        guide_email: str | None = None,
        reminder_minutes: list[int] | None = None,
    ) -> dict[str, Any]:
        if owner_confirmed is not True:
            raise GoogleCalendarInputError(
                "Creating a Calendar event requires explicit confirmation in the current request"
            )
        payload = _event_payload(
            title=title,
            start=start,
            end=end,
            time_zone=time_zone,
            idempotency_key=idempotency_key,
            description=description,
            location=location,
            session_type=session_type,
            venue_type=venue_type,
            guide_email=guide_email,
            reminder_minutes=reminder_minutes if reminder_minutes is not None else [60, 10],
        )
        event_id = payload["id"]
        send_updates = "all" if guide_email else "none"
        try:
            response = await self.client.insert_event(payload, send_updates=send_updates)
            if response.data.get("id") != event_id:
                raise GoogleCalendarError("Google Calendar returned an unexpected event ID")
            return _normalized(response.data, created=True, guide_email=guide_email)
        except GoogleCalendarError as error:
            if isinstance(error, GoogleCalendarConfigurationError):
                raise
            if error.status_code == 409:
                return await self._reconcile(
                    event_id, idempotency_key, payload, send_updates, allow_insert_retry=False
                )
            if error.status_code is None or error.status_code == 429 or error.status_code >= 500:
                return await self._reconcile(
                    event_id, idempotency_key, payload, send_updates, allow_insert_retry=True
                )
            raise

    async def _reconcile(
        self,
        event_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
        send_updates: str,
        *,
        allow_insert_retry: bool,
    ) -> dict[str, Any]:
        for attempt in range(2):
            try:
                existing = (await self.client.get_event(event_id)).data
            except GoogleCalendarError as error:
                if error.status_code != 404:
                    raise GoogleCalendarError(
                        "Could not reconcile Google Calendar event", error.status_code
                    ) from error
                if attempt == 0:
                    await asyncio.sleep(0)
                continue
            if not _owned(existing, idempotency_key):
                raise GoogleCalendarError(
                    "Calendar event ID belongs to another event", 409
                )
            response = await self.client.patch_event(
                event_id, payload, send_updates=send_updates
            )
            if response.data.get("id") != event_id:
                raise GoogleCalendarError("Google Calendar returned an unexpected event ID")
            guide = (
                payload["attendees"][0].get("email")
                if payload.get("attendees")
                else None
            )
            return _normalized(response.data, created=False, guide_email=guide)

        if not allow_insert_retry:
            raise GoogleCalendarError("Could not reconcile Google Calendar event", 404)
        try:
            response = await self.client.insert_event(payload, send_updates=send_updates)
        except GoogleCalendarError as error:
            if error.status_code == 409:
                return await self._reconcile(
                    event_id,
                    idempotency_key,
                    payload,
                    send_updates,
                    allow_insert_retry=False,
                )
            raise GoogleCalendarError(
                "Google Calendar write outcome is uncertain; retry later", error.status_code
            ) from error
        guide = payload.get("attendees", [{}])[0].get("email") if payload.get("attendees") else None
        return _normalized(response.data, created=True, guide_email=guide)

    async def get_session(self, event_id: str) -> dict[str, Any]:
        return _normalized((await self.client.get_event(event_id)).data, created=False)

    async def check_guide(self, event_id: str, guide_email: str) -> dict[str, Any]:
        expected = _validate_email(guide_email)
        event = (await self.client.get_event(event_id)).data
        attendees = event.get("attendees", [])
        if not isinstance(attendees, list):
            raise GoogleCalendarError("Google Calendar returned invalid attendee data")
        status = "not_invited"
        for attendee in attendees:
            if not isinstance(attendee, dict):
                continue
            if str(attendee.get("email", "")).strip().lower() == expected:
                status = GUIDE_STATUSES.get(attendee.get("responseStatus"), "pending")
                break
        return {
            "event_id": event.get("id"),
            "guide_status": status,
            "session_status": event.get("status"),
            "updated": event.get("updated"),
        }
