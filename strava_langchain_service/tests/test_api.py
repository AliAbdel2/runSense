import httpx
from fastapi.testclient import TestClient

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


def app_client(handler, api_key="local-key"):
    transport = httpx.MockTransport(handler)

    def factory(token, *, base_url):
        return StravaClient(token, base_url=base_url, transport=transport)

    settings = Settings(strava_access_token="strava-token", api_key=api_key)
    return TestClient(create_app(settings=settings, client_factory=factory))


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
    assert "strava_get_training_history" in {tool["name"] for tool in listed}

    history = client.get("/v1/strava/training-history", headers=auth).json()
    assert history["summary"]["activity_count"] == 1
    invoked = client.post(
        "/v1/tools/strava_get_training_history/invoke",
        json={"arguments": {"weeks": 4}},
        headers=auth,
    ).json()
    assert invoked["tool"] == "strava_get_training_history"
    assert invoked["result"]["activities"][0]["id"] == 99


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
