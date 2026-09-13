import json

import httpx
from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone

from app.calendar_client import GoogleCalendarClient
from app.config import Settings
from app.main import create_app
from app.strava_client import StravaClient


ACTIVITY = {
    "id": 99,
    "name": "Test Run",
    "sport_type": "Run",
    "start_date": "2026-09-12T07:00:00Z",
    "distance": 5000,
    "moving_time": 1800,
    "elapsed_time": 1820,
    "average_speed": 2.7777778,
    "has_heartrate": False,
}


def app_client(handler, api_key="local-key", calendar_handler=None):
    transport = httpx.MockTransport(handler)
    calendar_transport = httpx.MockTransport(
        calendar_handler
        or (lambda request: httpx.Response(500, json={"error": "unexpected calendar call"}))
    )

    def factory(token, *, base_url):
        return StravaClient(token, base_url=base_url, transport=transport)

    def calendar_factory(token, *, calendar_id, base_url):
        return GoogleCalendarClient(
            token,
            calendar_id=calendar_id,
            base_url=base_url,
            transport=calendar_transport,
        )

    settings = Settings(
        strava_access_token="strava-token",
        google_calendar_access_token="calendar-token",
        api_key=api_key,
    )
    return TestClient(
        create_app(
            settings=settings,
            client_factory=factory,
            calendar_client_factory=calendar_factory,
        )
    )


def test_postman_routes_are_protected_and_use_shared_tools():
    def handler(request):
        if request.url.path.endswith("/athlete/activities"):
            return httpx.Response(200, json=[ACTIVITY])
        return httpx.Response(200, json={"id": 7, "firstname": "Sara"})

    client = app_client(handler)
    auth = {"Authorization": "Bearer local-key"}
    assert client.get("/health").status_code == 200
    assert client.get("/v1/tools").status_code == 401
    listed = client.get("/v1/tools", headers=auth).json()["tools"]
    tool_names = {tool["name"] for tool in listed}
    assert "strava_get_training_history" in tool_names
    assert "calendar_create_session" in tool_names
    assert "runsense_get_live_metrics" in tool_names

    history = client.get("/v1/strava/training-history", headers=auth).json()
    assert history["summary"]["activity_count"] == 1
    invoked = client.post(
        "/v1/tools/strava_get_training_history/invoke",
        json={"arguments": {"weeks": 4}},
        headers=auth,
    ).json()
    assert invoked["tool"] == "strava_get_training_history"
    assert invoked["result"]["activities"][0]["id"] == 99

    started = client.post(
        "/v1/tools/runsense_start_session/invoke",
        json={"arguments": {"name": "Tool-started run"}},
        headers=auth,
    )
    assert started.status_code == 200
    assert started.json()["result"]["state"] == "active"
    current = client.post(
        "/v1/tools/runsense_get_live_metrics/invoke",
        json={"arguments": {}},
        headers=auth,
    )
    assert current.status_code == 200
    assert current.json()["result"]["name"] == "Tool-started run"


def test_raw_proxy_preserves_provider_status_metadata():
    client = app_client(
        lambda request: httpx.Response(
            200, json=[ACTIVITY], headers={"X-ReadRateLimit-Usage": "4,20"}
        )
    )
    response = client.get(
        "/v1/strava/activities",
        params={"after": 1, "per_page": 10},
        headers={"Authorization": "Bearer local-key"},
    )
    assert response.status_code == 200
    assert response.json()["meta"]["provider_status"] == 200
    assert response.json()["meta"]["rate_limits"]["read"]["used_15_min"] == 4


def test_provider_auth_error_is_safe_502():
    client = app_client(
        lambda request: httpx.Response(401, json={"message": "private provider detail"})
    )
    response = client.get(
        "/v1/strava/athlete", headers={"Authorization": "Bearer local-key"}
    )
    assert response.status_code == 502
    assert response.json() == {
        "detail": "Strava authentication failed",
        "provider": "strava",
        "provider_status": 401,
    }


def test_tool_validation_is_visible_to_postman():
    client = app_client(lambda request: httpx.Response(200, json={}))
    response = client.post(
        "/v1/tools/strava_get_activity_streams/invoke",
        json={"arguments": {"activity_id": 0, "keys": ["latlng"]}},
        headers={"Authorization": "Bearer local-key"},
    )
    assert response.status_code == 422


def test_calendar_tool_route_creates_an_event_with_the_same_contract():
    requests = []

    def calendar_handler(request):
        requests.append(request)
        return httpx.Response(200, json=json.loads(request.content))

    client = app_client(
        lambda request: httpx.Response(200, json={}),
        calendar_handler=calendar_handler,
    )
    response = client.post(
        "/v1/tools/calendar_create_session/invoke",
        headers={"Authorization": "Bearer local-key"},
        json={
            "arguments": {
                "title": "RunSense easy run",
                "start": "2026-09-15T09:00:00+02:00",
                "end": "2026-09-15T10:00:00+02:00",
                "time_zone": "Europe/Zurich",
                "idempotency_key": "sara:2026-09-15:easy",
                "owner_confirmed": True,
                "venue_type": "treadmill",
            }
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["created"] is True
    assert requests[0].url.params["sendUpdates"] == "none"


def test_calendar_input_error_is_a_safe_422():
    client = app_client(lambda request: httpx.Response(200, json={}))
    response = client.post(
        "/v1/calendar/events",
        headers={"Authorization": "Bearer local-key"},
        json={
            "title": "RunSense easy run",
            "start": "2026-09-15T10:00:00+02:00",
            "end": "2026-09-15T09:00:00+02:00",
            "idempotency_key": "sara:2026-09-15:easy",
            "owner_confirmed": True,
        },
    )
    assert response.status_code == 422


def test_live_session_requires_explicit_upload_and_is_idempotent():
    provider_calls = []

    def handler(request):
        provider_calls.append(request)
        if request.method == "POST" and request.url.path.endswith("/uploads"):
            assert b'name="data_type"' in request.content
            assert b"tcx" in request.content
            assert b"runsense-" in request.content
            return httpx.Response(
                201,
                json={
                    "id": 123,
                    "external_id": "runsense-test",
                    "status": "Your activity is still being processed.",
                    "activity_id": None,
                    "error": None,
                },
            )
        if request.url.path.endswith("/uploads/123"):
            return httpx.Response(
                200,
                json={
                    "id": 123,
                    "external_id": "runsense-test",
                    "status": "Your activity is ready.",
                    "activity_id": 999,
                    "error": None,
                },
            )
        return httpx.Response(200, json={})

    client = app_client(handler)
    auth = {"Authorization": "Bearer local-key"}
    started = datetime(2026, 9, 13, 8, tzinfo=timezone.utc)
    response = client.post(
        "/v1/sessions",
        headers=auth,
        json={"name": "Morning Run", "started_at": started.isoformat()},
    )
    assert response.status_code == 201
    session_id = response.json()["session_id"]
    samples = [
        {
            "timestamp": (started + timedelta(seconds=index * 5)).isoformat(),
            "latitude": 0,
            "longitude": index * 0.0001,
            "accuracy_m": 5,
            "heart_rate_bpm": 140 + index,
            "cadence_spm": 168 + index,
        }
        for index in range(3)
    ]
    live = client.post(
        f"/v1/sessions/{session_id}/samples", headers=auth, json={"samples": samples}
    )
    assert live.status_code == 200
    assert live.json()["live"]["current_pace_spoken"] == (
        "7 minutes 30 seconds per kilometre"
    )

    finished = client.post(
        f"/v1/sessions/{session_id}/finish",
        headers=auth,
        json={"at": (started + timedelta(seconds=12)).isoformat()},
    )
    assert finished.status_code == 200
    assert finished.json()["strava_upload"] is None
    exported = client.get(f"/v1/sessions/{session_id}/export.tcx", headers=auth)
    assert exported.status_code == 200
    assert exported.content.startswith(b"<?xml")

    refused = client.post(
        f"/v1/sessions/{session_id}/strava-upload",
        headers=auth,
        json={"owner_confirmed": False},
    )
    assert refused.status_code == 409
    uploaded = client.post(
        f"/v1/sessions/{session_id}/strava-upload",
        headers=auth,
        json={"owner_confirmed": True},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["upload"]["id"] == 123
    repeated = client.post(
        f"/v1/sessions/{session_id}/strava-upload",
        headers=auth,
        json={"owner_confirmed": True},
    )
    assert repeated.status_code == 200
    assert repeated.json()["reused"] is True
    assert len([call for call in provider_calls if call.method == "POST"]) == 1

    status = client.get(f"/v1/sessions/{session_id}/strava-upload", headers=auth)
    assert status.status_code == 200
    assert status.json()["upload"]["activity_id"] == 999
