import asyncio
from datetime import datetime, timezone

import httpx

from app.service import StravaService
from app.strava_client import StravaClient
from app.tools import build_strava_tools


def run(coro):
    return asyncio.run(coro)


def sample(activity_id=11, distance=5000, sport="Run", start="2026-09-12T07:00:00Z"):
    return {
        "id": activity_id,
        "name": "Morning Run",
        "sport_type": sport,
        "start_date": start,
        "distance": distance,
        "moving_time": 1800,
        "elapsed_time": 1850,
        "total_elevation_gain": 30,
        "average_speed": 2.7777778,
        "has_heartrate": True,
        "average_heartrate": 148,
        "max_heartrate": 170,
        "map": {"summary_polyline": "must-not-reach-agent"},
    }


def test_history_uses_authorization_normalizes_runs_and_reports_limits():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json=[sample(), sample(12, sport="Ride")],
            headers={
                "X-RateLimit-Limit": "200,2000",
                "X-RateLimit-Usage": "1,2",
                "X-ReadRateLimit-Limit": "100,1000",
                "X-ReadRateLimit-Usage": "1,2",
            },
        )

    async def operation():
        async with StravaClient("secret", transport=httpx.MockTransport(handler)) as client:
            return await StravaService(client).training_history(10, 20)

    result = run(operation())
    assert requests[0].headers["authorization"] == "Bearer secret"
    assert requests[0].url.path == "/api/v3/athlete/activities"
    assert requests[0].url.params["after"] == "10"
    assert result["summary"] == {
        "activity_count": 1,
        "total_distance_km": 5.0,
        "activities_with_heartrate": 1,
    }
    assert result["activities"][0]["pace_min_per_km"] == 6.0
    assert "map" not in result["activities"][0]
    assert result["meta"]["rate_limits"]["read"]["limit_daily"] == 1000


def test_verify_run_prefers_start_time_and_reports_cut_short():
    rows = [
        sample(21, 5000, start="2026-09-12T05:00:00Z"),
        sample(22, 3000, start="2026-09-12T07:02:00Z"),
    ]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=rows))

    async def operation():
        async with StravaClient("secret", transport=transport) as client:
            return await StravaService(client).verify_completed_run(
                datetime(2026, 9, 12, 7, tzinfo=timezone.utc), 5000
            )

    result = run(operation())
    assert result["activity"]["id"] == 22
    assert result["comparison"] == {
        "start_delta_seconds": 120.0,
        "distance_completion_ratio": 0.6,
    }


def test_langchain_tools_call_the_same_service_contract():
    def handler(request):
        if request.url.path.endswith("/streams"):
            assert request.url.params["keys"] == "time,heartrate"
            return httpx.Response(200, json={"time": {"data": [0]}, "heartrate": {"data": [140]}})
        return httpx.Response(200, json=[sample()])

    async def operation():
        async with StravaClient("secret", transport=httpx.MockTransport(handler)) as client:
            tools = {tool.name: tool for tool in build_strava_tools(StravaService(client))}
            history = await tools["strava_get_training_history"].ainvoke({"weeks": 4})
            streams = await tools["strava_get_activity_streams"].ainvoke(
                {"activity_id": 11, "keys": ["time", "heartrate"]}
            )
            return history, streams

    history, streams = run(operation())
    assert history["summary"]["activity_count"] == 1
    assert streams["data"]["heartrate"]["data"] == [140]


def test_location_stream_is_rejected_before_provider_call():
    calls = []
    transport = httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200, json={}))

    async def operation():
        async with StravaClient("secret", transport=transport) as client:
            await StravaService(client).streams(11, ["latlng"])

    try:
        run(operation())
    except Exception as exc:
        assert "latlng" in str(exc)
    else:
        raise AssertionError("expected latlng rejection")
    assert calls == []


def test_provider_error_does_not_leak_response_or_token():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(401, json={"message": "secret-token is invalid"})
    )

    async def operation():
        async with StravaClient("secret-token", transport=transport) as client:
            await client.get_athlete()

    try:
        run(operation())
    except Exception as exc:
        assert "secret-token" not in str(exc)
        assert "provider status 401" in str(exc)
    else:
        raise AssertionError("expected provider failure")
