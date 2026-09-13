import asyncio
import json
from datetime import datetime

import httpx
from langchain_core.messages import AIMessage

from app.calendar_client import (
    GoogleCalendarClient,
    GoogleCalendarConfigurationError,
    GoogleCalendarError,
)
from app.calendar_service import CalendarService, event_id_for
from app.calendar_tools import build_calendar_tools
from app.agent import run_agent


def run(coro):
    return asyncio.run(coro)


def session(**overrides):
    value = {
        "title": "RunSense intervals",
        "start": datetime.fromisoformat("2026-09-15T09:00:00+02:00"),
        "end": datetime.fromisoformat("2026-09-15T10:00:00+02:00"),
        "time_zone": "Europe/Zurich",
        "idempotency_key": "sara:2026-09-15:intervals",
        "owner_confirmed": True,
        "description": "Four by eight hundred metres. Guide required.",
        "location": "Letzigrund track",
        "session_type": "intervals",
        "venue_type": "track",
        "guide_email": "guide@example.com",
        "reminder_minutes": [60, 10],
    }
    value.update(overrides)
    return value


def test_create_tool_writes_invite_reminders_and_private_idempotency_marker():
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json={**body, "htmlLink": "https://calendar.test/event"})

    async def operation():
        async with GoogleCalendarClient(
            "google-token", transport=httpx.MockTransport(handler)
        ) as client:
            tools = {
                tool.name: tool for tool in build_calendar_tools(CalendarService(client))
            }
            return await tools["calendar_create_session"].ainvoke(session())

    result = run(operation())
    assert result["created"] is True
    assert result["event_id"] == event_id_for("sara:2026-09-15:intervals")
    assert result["guide_status"] == "pending"
    request = requests[0]
    assert request.method == "POST"
    assert request.url.params["sendUpdates"] == "all"
    assert request.headers["authorization"] == "Bearer google-token"
    body = json.loads(request.content)
    assert body["attendees"] == [{"email": "guide@example.com"}]
    assert body["status"] == "tentative"
    assert body["reminders"]["overrides"] == [
        {"method": "popup", "minutes": 60},
        {"method": "popup", "minutes": 10},
    ]
    assert body["extendedProperties"]["private"]["runsense_managed"] == "true"
    assert "sara:2026" not in json.dumps(body)


def test_create_without_guide_suppresses_calendar_notifications():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=json.loads(request.content))

    async def operation():
        async with GoogleCalendarClient(
            "token", transport=httpx.MockTransport(handler)
        ) as client:
            return await CalendarService(client).create_session(
                **session(guide_email=None, venue_type="treadmill")
            )

    result = run(operation())
    assert result["created"] is True
    assert requests[0].url.params["sendUpdates"] == "none"
    assert "attendees" not in json.loads(requests[0].content)


def test_explicit_confirmation_is_required_before_provider_call():
    requests = []
    transport = httpx.MockTransport(
        lambda request: requests.append(request) or httpx.Response(200, json={})
    )

    async def operation():
        async with GoogleCalendarClient("token", transport=transport) as client:
            await CalendarService(client).create_session(
                **session(owner_confirmed=False)
            )

    try:
        run(operation())
    except Exception as exc:
        assert "explicit confirmation" in str(exc)
    else:
        raise AssertionError("expected confirmation gate")
    assert requests == []


def test_duplicate_create_reconciles_owned_event_and_patches_once():
    requests = []
    expected_id = event_id_for("sara:2026-09-15:intervals")

    def handler(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(409)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": expected_id,
                    "extendedProperties": {
                        "private": {
                            "runsense_managed": "true",
                            "runsense_idempotency_hash": json.loads(
                                requests[0].content
                            )["extendedProperties"]["private"][
                                "runsense_idempotency_hash"
                            ],
                        }
                    },
                },
            )
        return httpx.Response(200, json=json.loads(request.content))

    async def operation():
        async with GoogleCalendarClient(
            "token", transport=httpx.MockTransport(handler)
        ) as client:
            return await CalendarService(client).create_session(**session())

    result = run(operation())
    assert result["created"] is False
    assert [request.method for request in requests] == ["POST", "GET", "PATCH"]
    assert requests[-1].url.params["sendUpdates"] == "all"


def test_duplicate_create_never_overwrites_an_unowned_event():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(409)
        return httpx.Response(200, json={"id": event_id_for("sara:2026-09-15:intervals")})

    async def operation():
        async with GoogleCalendarClient(
            "token", transport=httpx.MockTransport(handler)
        ) as client:
            await CalendarService(client).create_session(**session())

    try:
        run(operation())
    except GoogleCalendarError as exc:
        assert exc.status_code == 409
        assert "another event" in str(exc)
    else:
        raise AssertionError("expected ownership conflict")


def test_check_guide_returns_only_the_requested_attendee_status():
    event_id = event_id_for("sara:2026-09-15:intervals")
    provider_event = {
        "id": event_id,
        "status": "confirmed",
        "attendees": [
            {"email": "someone@example.com", "responseStatus": "declined"},
            {"email": "GUIDE@example.com", "responseStatus": "accepted"},
        ],
    }

    async def operation():
        async with GoogleCalendarClient(
            "token",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=provider_event)
            ),
        ) as client:
            tools = {
                tool.name: tool for tool in build_calendar_tools(CalendarService(client))
            }
            return await tools["calendar_check_guide"].ainvoke(
                {"event_id": event_id, "guide_email": "guide@example.com"}
            )

    assert run(operation()) == {
        "event_id": event_id,
        "guide_status": "accepted",
        "session_status": "confirmed",
        "updated": None,
    }


def test_provider_error_is_sanitized():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            401, json={"error": {"message": "google-token private detail"}}
        )
    )

    async def operation():
        async with GoogleCalendarClient("google-token", transport=transport) as client:
            await client.get_event("runsense12345")

    try:
        run(operation())
    except GoogleCalendarError as exc:
        assert exc.status_code == 401
        assert "google-token" not in str(exc)
        assert "authentication failed" in str(exc)
    else:
        raise AssertionError("expected provider failure")


def test_missing_calendar_token_is_reported_without_reconciliation_noise():
    async def operation():
        async with GoogleCalendarClient("") as client:
            await CalendarService(client).create_session(**session())

    try:
        run(operation())
    except GoogleCalendarConfigurationError as exc:
        assert "GOOGLE_CALENDAR_ACCESS_TOKEN" in str(exc)
        assert "reconcile" not in str(exc).lower()
    else:
        raise AssertionError("expected missing Calendar configuration")


def test_langchain_agent_can_execute_calendar_create_tool(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json=body)

    class FakeLLM:
        def __init__(self, **_kwargs):
            self.calls = 0

        def bind_tools(self, _tools):
            return self

        async def ainvoke(self, _messages):
            self.calls += 1
            if self.calls == 1:
                args = session(guide_email=None, venue_type="treadmill")
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "calendar_create_session",
                            "args": args,
                            "id": "call-1",
                            "type": "tool_call",
                        }
                    ],
                )
            return AIMessage(content="The treadmill session is scheduled.")

    monkeypatch.setattr("app.agent.ChatAnthropic", FakeLLM)

    async def operation():
        async with GoogleCalendarClient(
            "token", transport=httpx.MockTransport(handler)
        ) as client:
            return await run_agent(
                "Create this treadmill training session.",
                build_calendar_tools(CalendarService(client)),
                api_key="anthropic-key",
                model="test-model",
            )

    result = run(operation())
    assert result["answer"] == "The treadmill session is scheduled."
    assert result["tool_calls"][0]["tool"] == "calendar_create_session"
    assert result["tool_calls"][0]["status"] == "success"
    assert requests and requests[0].method == "POST"
