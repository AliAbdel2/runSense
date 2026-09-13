"""Small, typed HTTP clients for the services used by RunSense.

The clients deliberately accept an ``httpx`` transport.  This keeps the
integration boundary easy to test without credentials or live network calls.
Only OAuth access-token mode is implemented here; token bootstrap and refresh
belong to the application authentication layer.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import math
import os
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Mapping
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx


@dataclass(frozen=True)
class Settings:
    """Configuration for external integrations.

    Empty environment variables are treated as absent.  A credential is never
    included in an exception or log message by this module.
    """

    google_access_token: str | None = None
    sheets_spreadsheet_id: str | None = None
    sheets_range: str = "Training!A1:E100"
    google_calendar_id: str = "primary"
    notion_api_key: str | None = None
    notion_data_source_id: str | None = None
    notion_version: str = "2026-03-11"
    notion_title_property: str = "Name"
    notion_plan_id_property: str = "Plan ID"
    notion_summary_property: str = "Summary"
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None
    elevenlabs_model_id: str | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        def optional(name: str) -> str | None:
            value = os.getenv(name)
            return value if value else None

        return cls(
            google_access_token=optional("GOOGLE_ACCESS_TOKEN"),
            sheets_spreadsheet_id=optional("SHEETS_SPREADSHEET_ID"),
            sheets_range=os.getenv("SHEETS_RANGE") or cls.sheets_range,
            google_calendar_id=os.getenv("GOOGLE_CALENDAR_ID") or cls.google_calendar_id,
            notion_api_key=optional("NOTION_API_KEY"),
            notion_data_source_id=optional("NOTION_DATA_SOURCE_ID"),
            notion_version=os.getenv("NOTION_VERSION") or cls.notion_version,
            notion_title_property=os.getenv("NOTION_TITLE_PROPERTY") or cls.notion_title_property,
            notion_plan_id_property=os.getenv("NOTION_PLAN_ID_PROPERTY") or cls.notion_plan_id_property,
            notion_summary_property=os.getenv("NOTION_SUMMARY_PROPERTY") or cls.notion_summary_property,
            elevenlabs_api_key=optional("ELEVENLABS_API_KEY"),
            elevenlabs_voice_id=optional("ELEVENLABS_VOICE_ID"),
            elevenlabs_model_id=optional("ELEVENLABS_MODEL_ID"),
            twilio_account_sid=optional("TWILIO_ACCOUNT_SID"),
            twilio_auth_token=optional("TWILIO_AUTH_TOKEN"),
            twilio_from_number=optional("TWILIO_FROM_NUMBER"),
        )


class IntegrationError(RuntimeError):
    """A safe, user-facing integration failure.

    ``message`` is intentionally sanitized and contains no response body,
    request URL query, authorization token, or provider exception details.
    """

    def __init__(self, provider: str, message: str, status_code: int | None = None):
        self.provider = provider
        self.status_code = status_code
        self.message = message
        self.safe_message = message
        suffix = f" (status {status_code})" if status_code is not None else ""
        super().__init__(f"{provider}: {message}{suffix}")


class _Client:
    provider = "integration"
    max_attempts = 4
    retry_after_cap = 2.0

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._client = httpx.AsyncClient(transport=transport, timeout=15.0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None,
                       params: Mapping[str, str] | None = None, json: Any = None,
                       content: Any = None, retry_statuses: bool = True) -> httpx.Response:
        for attempt in range(self.max_attempts):
            try:
                response = await self._client.request(
                    method, url, headers=headers, params=params, json=json, content=content
                )
            except httpx.HTTPError as exc:
                # Do not expose provider URLs, request data, or exception text.
                raise IntegrationError(self.provider, "request failed") from exc

            should_retry = retry_statuses and (
                response.status_code == 429 or response.status_code >= 500
            )
            if should_retry and attempt < self.max_attempts - 1:
                retry_after = _retry_after(response)
                delay = min(self.retry_after_cap, retry_after) if retry_after is not None else min(
                    self.retry_after_cap, 0.1 * (2**attempt)
                )
                await asyncio.sleep(delay)
                continue

            if response.status_code >= 400:
                raise IntegrationError(self.provider, "request failed", response.status_code)
            return response

        raise IntegrationError(self.provider, "request failed")

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            value = response.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise IntegrationError(self.provider, "provider returned invalid JSON", response.status_code) from exc
        if not isinstance(value, dict):
            raise IntegrationError(self.provider, "provider returned invalid JSON", response.status_code)
        return value


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, parsed)


def _require(value: str | None, provider: str, setting: str) -> str:
    if not value:
        raise IntegrationError(provider, f"missing configuration: {setting}")
    return value


def _google_headers(settings: Settings) -> dict[str, str]:
    token = _require(settings.google_access_token, "google", "GOOGLE_ACCESS_TOKEN")
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


class SheetsClient(_Client):
    provider = "google sheets"
    base_url = "https://sheets.googleapis.com/v4"

    async def get_activities(self) -> list[dict[str, Any]]:
        spreadsheet_id = _require(self.settings.sheets_spreadsheet_id, self.provider, "SHEETS_SPREADSHEET_ID")
        response = await self._request(
            "GET",
            f"{self.base_url}/spreadsheets/{spreadsheet_id}/values/{self.settings.sheets_range}",
            headers=_google_headers(self.settings),
        )
        body = self._json(response)
        rows = body.get("values", [])
        if not isinstance(rows, list):
            raise IntegrationError(self.provider, "provider returned invalid activity data", response.status_code)

        activities: list[dict[str, Any]] = []
        for index, raw_row in enumerate(rows):
            if not isinstance(raw_row, list) or not raw_row:
                continue
            # A header is convenient for a human-authored sheet and is not an
            # activity.  A header in any position other than the first row is
            # treated as malformed input.
            if index == 0 and [str(x).strip().lower() for x in raw_row[:5]] == [
                "date", "km", "kind", "completed", "source"
            ]:
                continue
            if len(raw_row) < 5:
                raise IntegrationError(self.provider, "activity row is missing required columns")
            row = raw_row[:5]
            source = str(row[4]).strip()
            if source != "athlete_authored":
                raise IntegrationError(self.provider, "activity source is not athlete authored")
            try:
                km = float(row[1])
            except (TypeError, ValueError) as exc:
                raise IntegrationError(self.provider, "activity distance is invalid") from exc
            if not math.isfinite(km) or km < 0:
                raise IntegrationError(self.provider, "activity distance is invalid")
            try:
                activity_date = date.fromisoformat(str(row[0]).strip())
            except (TypeError, ValueError) as exc:
                raise IntegrationError(self.provider, "activity date is invalid") from exc
            activities.append({
                "date": activity_date.isoformat(),
                "km": km,
                "kind": str(row[2]).strip(),
                "completed": _bool_value(row[3]),
                "source": source,
            })
        return activities


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y", "done", "completed"}:
        return True
    if normalized in {"false", "0", "no", "n", "", "pending", "planned"}:
        return False
    raise IntegrationError("google sheets", "activity completion value is invalid")


class CalendarClient(_Client):
    provider = "google calendar"
    base_url = "https://www.googleapis.com/calendar/v3"
    timezone = "Europe/Zurich"

    async def get_session(self, event_id: str) -> dict[str, Any]:
        calendar_id = _require(self.settings.google_calendar_id, self.provider, "GOOGLE_CALENDAR_ID")
        response = await self._request(
            "GET",
            f"{self.base_url}/calendars/{calendar_id}/events/{event_id}",
            headers=_google_headers(self.settings),
        )
        return self._json(response)

    async def upsert_session(self, session: Mapping[str, Any]) -> dict[str, Any]:
        _validate_session(session)
        calendar_id = _require(self.settings.google_calendar_id, self.provider, "GOOGLE_CALENDAR_ID")
        event_id = _event_id(str(session["id"]))
        payload = _calendar_event(session, event_id)
        headers = {**_google_headers(self.settings), "Content-Type": "application/json"}
        insert_url = f"{self.base_url}/calendars/{calendar_id}/events"
        try:
            return await self._create_event(
                event_id, insert_url, headers, payload
            )
        except IntegrationError as error:
            if error.status_code == 409:
                return await self._reconcile_event(
                    calendar_id, event_id, payload, headers, allow_insert_retry=False
                )
            # A 5xx or transport timeout may mean Google accepted the insert
            # before the response was lost.  Reconcile before retrying.
            if error.status_code is None or error.status_code == 429 or error.status_code >= 500:
                return await self._reconcile_event(
                    calendar_id, event_id, payload, headers, allow_insert_retry=True
                )
            raise

    async def _create_event(self, event_id: str, insert_url: str,
                            headers: Mapping[str, str], payload: Mapping[str, Any]) -> dict[str, Any]:
        response = await self._request(
                "POST", insert_url, headers=headers,
                params={"sendUpdates": "none"}, json=payload,
                # An uncertain Calendar insert is reconciled by deterministic
                # ID; blindly retrying a non-idempotent request is unsafe.
                retry_statuses=False,
            )
        body = self._json(response)
        if body.get("id") != event_id:
            raise IntegrationError(self.provider, "provider returned an unexpected event ID")
        return body

    async def _patch_event(self, calendar_id: str, event_id: str,
                           headers: Mapping[str, str], payload: Mapping[str, Any]) -> dict[str, Any]:
        response = await self._request(
            "PATCH",
            f"{self.base_url}/calendars/{calendar_id}/events/{event_id}",
            headers=headers,
            params={"sendUpdates": "none"}, json=payload,
        )
        body = self._json(response)
        if body.get("id") != event_id:
            raise IntegrationError(self.provider, "provider returned an unexpected event ID")
        return body

    async def _reconcile_event(self, calendar_id: str, event_id: str,
                               payload: Mapping[str, Any], headers: Mapping[str, str],
                               *, allow_insert_retry: bool) -> dict[str, Any]:
        session_id = str(payload["extendedProperties"]["private"]["runsense_session_id"])
        # Calendar read-after-write can be briefly eventually consistent. Two
        # bounded GETs are enough to cover that window without an unbounded
        # retry loop.
        for attempt in range(2):
            try:
                existing = await self.get_session(event_id)
            except IntegrationError as error:
                if error.status_code != 404:
                    raise IntegrationError(
                        self.provider, "could not reconcile existing event", error.status_code
                    ) from error
                if attempt == 0:
                    await asyncio.sleep(0)
                continue
            if existing.get("id") not in (None, event_id):
                raise IntegrationError(self.provider, "provider returned an unexpected event ID")
            # A deterministic ID is useful only with ownership verification.
            if not _owned_event(existing, session_id):
                raise IntegrationError(self.provider, "event ID belongs to another event", 409)
            return await self._patch_event(calendar_id, event_id, headers, payload)

        if not allow_insert_retry:
            raise IntegrationError(self.provider, "could not reconcile existing event", 404)

        # One final deterministic-ID insert is safe after bounded GET misses.
        try:
            return await self._create_event(
                event_id,
                f"{self.base_url}/calendars/{calendar_id}/events",
                headers,
                payload,
            )
        except IntegrationError as error:
            if error.status_code == 409:
                # The retry raced with another writer; reconcile once without
                # starting another insert cycle.
                return await self._reconcile_event(
                    calendar_id, event_id, payload, headers, allow_insert_retry=False
                )
            raise IntegrationError(self.provider, "calendar write outcome is uncertain; retry later", error.status_code) from error


def _event_id(session_id: str) -> str:
    try:
        return uuid.UUID(session_id).hex
    except (ValueError, AttributeError):
        # Keep caller-provided hexadecimal IDs stable while making malformed
        # IDs deterministic and acceptable to Calendar's ID constraints.
        candidate = re.sub(r"[^a-z0-9]", "", session_id.lower())
        if len(candidate) >= 5 and candidate:
            return candidate
        return "runsense" + hashlib.sha256(session_id.encode()).hexdigest()[:24]


def _owned_event(event: Mapping[str, Any], session_id: str) -> bool:
    private = event.get("extendedProperties", {}).get("private", {})
    return isinstance(private, Mapping) and private.get("runsense_session_id") == session_id


def _validate_session(session: Mapping[str, Any]) -> None:
    required = {"id", "athlete_id", "date", "kind", "km", "venue", "guide_status", "spoken_summary", "rationale"}
    if not required.issubset(session):
        raise IntegrationError("google calendar", "session is missing required fields")
    if session["kind"] not in {"easy", "intervals", "long", "rest"}:
        raise IntegrationError("google calendar", "session kind is invalid")
    if session["venue"] not in {"treadmill", "track", "park"}:
        raise IntegrationError("google calendar", "session venue is invalid")
    if session["guide_status"] not in {"accepted", "pending", "declined", "not_required"}:
        raise IntegrationError("google calendar", "guide status is invalid")
    try:
        date.fromisoformat(str(session["date"]))
        km = float(session["km"])
        if not math.isfinite(km) or km < 0:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise IntegrationError("google calendar", "session date or distance is invalid") from exc


def _calendar_event(session: Mapping[str, Any], event_id: str) -> dict[str, Any]:
    session_date = date.fromisoformat(str(session["date"]))
    # ``start_time`` is an optional extension for easy sessions; the default
    # is the deterministic 09:00 local schedule used by the demo.
    start_text = str(session.get("start_time", "09:00"))
    try:
        start_time = time.fromisoformat(start_text)
    except ValueError as exc:
        raise IntegrationError("google calendar", "session start time is invalid") from exc
    zone = ZoneInfo("Europe/Zurich")
    start = datetime.combine(session_date, start_time, tzinfo=zone)
    end = start + timedelta(hours=1)
    kind = str(session["kind"])
    summary = f"RunSense {kind} run"
    spoken = str(session["spoken_summary"])
    rationale = str(session["rationale"])
    description = f"{spoken}\n\nWhy: {rationale}\nVenue: {session['venue']}"
    return {
        "id": event_id,
        "summary": summary,
        "description": description,
        "location": str(session["venue"]),
        "start": {"dateTime": start.isoformat(), "timeZone": "Europe/Zurich"},
        "end": {"dateTime": end.isoformat(), "timeZone": "Europe/Zurich"},
        "extendedProperties": {
            "private": {
                "runsense_managed": "true",
                "runsense_session_id": str(session["id"]),
                "runsense_athlete_id": str(session["athlete_id"]),
                "runsense_guide_status": str(session["guide_status"]),
            }
        },
    }


class NotionClient(_Client):
    provider = "notion"
    base_url = "https://api.notion.com/v1"

    def _headers(self) -> dict[str, str]:
        key = _require(self.settings.notion_api_key, self.provider, "NOTION_API_KEY")
        return {
            "Authorization": f"Bearer {key}",
            "Notion-Version": self.settings.notion_version,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _find_plan(self, plan_id: str) -> dict[str, Any] | None:
        source_id = _require(self.settings.notion_data_source_id, self.provider, "NOTION_DATA_SOURCE_ID")
        response = await self._request(
            "POST",
            f"{self.base_url}/data_sources/{source_id}/query",
            headers=self._headers(),
            json={"filter": {"property": self.settings.notion_plan_id_property,
                              "rich_text": {"equals": plan_id}}},
        )
        body = self._json(response)
        results = body.get("results", [])
        if not isinstance(results, list):
            raise IntegrationError(self.provider, "provider returned invalid plan data", response.status_code)
        if len(results) > 1:
            raise IntegrationError(self.provider, "multiple plans have the same Plan ID")
        return results[0] if results else None

    async def get_plan(self, page_id: str) -> dict[str, Any]:
        """Retrieve a plan page for post-write verification."""
        response = await self._request(
            "GET", f"{self.base_url}/pages/{page_id}", headers=self._headers()
        )
        return self._json(response)

    async def upsert_plan(self, plan: Mapping[str, Any]) -> dict[str, Any]:
        _validate_plan(plan)
        plan_id = str(plan["id"])
        existing = await self._find_plan(plan_id)
        headers = self._headers()
        properties = _notion_properties(self.settings, plan)
        if existing is not None:
            page_id = existing.get("id")
            if not page_id:
                raise IntegrationError(self.provider, "provider returned an invalid plan page")
            response = await self._request(
                "PATCH", f"{self.base_url}/pages/{page_id}",
                headers=headers, json={"properties": properties},
            )
            return self._json(response)

        create_payload = {
            "parent": {"data_source_id": _require(self.settings.notion_data_source_id, self.provider, "NOTION_DATA_SOURCE_ID")},
            "properties": properties,
        }
        try:
            response = await self._request(
                "POST", f"{self.base_url}/pages", headers=headers, json=create_payload,
                # A page create is not safely retryable: the server may have
                # accepted it even when the client saw a timeout/5xx.
                retry_statuses=False,
            )
            return self._json(response)
        except IntegrationError as error:
            # Reconcile every ambiguous outcome before allowing a caller to
            # retry.  This includes a conflict, throttling/server failure, and
            # transport failures where the server may have committed first.
            ambiguous = (
                error.status_code is None
                or error.status_code in {408, 409, 429}
                or error.status_code >= 500
            )
            if not ambiguous:
                raise
            # Another serialized writer may have created it after our lookup.
            # Re-query and patch the reconciled page; never blindly create again.
            try:
                reconciled = await self._find_plan(plan_id)
            except IntegrationError as reconcile_error:
                raise IntegrationError(
                    self.provider, "could not reconcile created plan", reconcile_error.status_code
                ) from error
            if reconciled is None or not reconciled.get("id"):
                raise IntegrationError(self.provider, "could not reconcile created plan", 409) from error
            response = await self._request(
                "PATCH", f"{self.base_url}/pages/{reconciled['id']}",
                headers=headers, json={"properties": properties},
            )
            return self._json(response)


def _validate_plan(plan: Mapping[str, Any]) -> None:
    required = {"id", "week_start", "athlete_name", "rationale", "week_km", "sessions"}
    if not required.issubset(plan) or not isinstance(plan["sessions"], list):
        raise IntegrationError("notion", "plan is missing required fields")
    try:
        date.fromisoformat(str(plan["week_start"]))
        week_km = float(plan["week_km"])
        if not math.isfinite(week_km) or week_km < 0:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise IntegrationError("notion", "plan week or distance is invalid") from exc


def _notion_text(value: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": value}}]


def _notion_properties(settings: Settings, plan: Mapping[str, Any]) -> dict[str, Any]:
    session_lines = []
    for session in plan["sessions"]:
        if isinstance(session, Mapping):
            session_lines.append(f"{session.get('date', '')} {session.get('kind', '')} {session.get('km', '')} km")
        else:
            session_lines.append(str(session))
    summary = (
        f"{plan['rationale']}\n\n"
        f"Week of {plan['week_start']} · {float(plan['week_km']):g} km\n" +
        "\n".join(session_lines)
    )
    return {
        settings.notion_title_property: {"title": _notion_text(f"{plan['athlete_name']} — week of {plan['week_start']}")},
        settings.notion_plan_id_property: {"rich_text": _notion_text(str(plan["id"]))},
        settings.notion_summary_property: {"rich_text": _notion_text(summary)},
    }


class ElevenLabsClient(_Client):
    provider = "elevenlabs"
    base_url = "https://api.elevenlabs.io/v1"

    async def synthesize(self, text: str) -> bytes:
        if not isinstance(text, str) or not text.strip():
            raise IntegrationError(self.provider, "speech text is empty")
        key = _require(self.settings.elevenlabs_api_key, self.provider, "ELEVENLABS_API_KEY")
        voice_id = _require(self.settings.elevenlabs_voice_id, self.provider, "ELEVENLABS_VOICE_ID")
        model_id = _require(self.settings.elevenlabs_model_id, self.provider, "ELEVENLABS_MODEL_ID")
        response = await self._request(
            "POST",
            f"{self.base_url}/text-to-speech/{voice_id}",
            headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
            json={"text": text, "model_id": model_id},
        )
        if not response.content:
            raise IntegrationError(self.provider, "provider returned empty audio", response.status_code)
        return response.content


class TwilioClient(_Client):
    provider = "twilio"
    base_url = "https://api.twilio.com/2010-04-01"

    async def send_sms(self, to: str, body: str) -> dict[str, Any]:
        """Send one SMS and return the provider's message record (sid, status)."""
        if not isinstance(to, str) or not to.strip():
            raise IntegrationError(self.provider, "destination phone number is empty")
        if not isinstance(body, str) or not body.strip():
            raise IntegrationError(self.provider, "message body is empty")
        account_sid = _require(self.settings.twilio_account_sid, self.provider, "TWILIO_ACCOUNT_SID")
        auth_token = _require(self.settings.twilio_auth_token, self.provider, "TWILIO_AUTH_TOKEN")
        sender = _require(self.settings.twilio_from_number, self.provider, "TWILIO_FROM_NUMBER")
        credentials = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
        response = await self._request(
            "POST",
            f"{self.base_url}/Accounts/{account_sid}/Messages.json",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            content=urlencode({"To": to.strip(), "From": sender, "Body": body}),
            # Twilio's Messages API offers no idempotency key, so a retried send
            # is a second delivered message.  Surface the uncertainty instead.
            retry_statuses=False,
        )
        return self._json(response)


__all__ = [
    "CalendarClient",
    "ElevenLabsClient",
    "IntegrationError",
    "NotionClient",
    "Settings",
    "SheetsClient",
    "TwilioClient",
]
