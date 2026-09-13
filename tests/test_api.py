import asyncio

from fastapi.testclient import TestClient

from runsense.db import TypedStore
from runsense.delivery import write_clip
from runsense.main import create_app
from runsense.store import Store


def test_demo_complete_loop_and_durable_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNSENSE_MODE", "demo")
    path = str(tmp_path / "test.sqlite3")
    client = TestClient(create_app(path))
    payload = client.post("/api/plan", json={"scenario": "calendar_retry"}).json()
    assert payload["mode"] == "demo"
    assert payload["validation"]["passed"]
    assert len(payload["calendar_events"]) == 4
    assert any(t["status"] == "retrying" for t in payload["trace"])
    assert "history" not in payload
    restarted = TestClient(create_app(path))
    assert restarted.get(f"/api/runs/{payload['run_id']}").json() == payload
    assert Store(path).count_actions("demo_calendar") == 4


def test_demo_cannot_write_external_apps(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNSENSE_MODE", "demo")
    client = TestClient(create_app(str(tmp_path / "test.sqlite3")))
    assert client.post("/api/commit", json={"run_id": "x", "approved": True}).status_code == 409


def test_live_requires_auth_and_review(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNSENSE_MODE", "live")
    monkeypatch.setenv("RUNSENSE_ADMIN_TOKEN", "test-secret")
    client = TestClient(create_app(str(tmp_path / "test.sqlite3")))
    assert client.post("/api/plan", json={}).status_code == 401
    assert client.get("/api/runs/x").status_code == 401
    assert client.post("/api/commit", json={"run_id": "x"}, headers={"Authorization": "Bearer test-secret"}).status_code == 400
    assert client.post("/api/commit", json={"run_id": "x", "approved": True}, headers={"Authorization": "Bearer test-secret"}).status_code == 422


def test_foreign_origin_and_host_rejected(tmp_path):
    client = TestClient(create_app(str(tmp_path / "test.sqlite3")))
    assert client.post("/api/plan", json={}, headers={"Origin": "https://example.com"}).status_code == 403
    assert client.get("/api/status", headers={"Host": "evil.example"}).status_code == 400


def test_configured_lan_host_is_allowed_for_phone_testing(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNSENSE_ALLOWED_HOSTS", "localhost,127.0.0.1,192.168.1.23")
    client = TestClient(create_app(str(tmp_path / "test.sqlite3")))
    assert client.get("/", headers={"Host": "192.168.1.23"}).status_code == 200
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 400


def test_status_does_not_claim_connected_when_only_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "never-output-this")
    client = TestClient(create_app(str(tmp_path / "test.sqlite3")))
    response = client.get("/api/status")
    assert "never-output-this" not in response.text
    assert response.json()["integrations"][1]["status"] == "configured_unverified"


def test_status_reports_optional_sms_without_claiming_a_connection(tmp_path, monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC-never-output-this")
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    client = TestClient(create_app(str(tmp_path / "test.sqlite3")))
    integrations = {entry["name"]: entry for entry in client.get("/api/status").json()["integrations"]}
    # Partially configured is not configured, and the value itself is never echoed.
    assert integrations["Twilio"]["status"] == "not_connected"
    assert "AC-never-output-this" not in client.get("/api/status").text
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "token")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15550000000")
    assert client.get("/api/status").json()["integrations"][4]["status"] == "configured_unverified"


def test_audio_route_serves_cached_clip_and_404s_unknown_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNSENSE_AUDIO_DIR", str(tmp_path / "audio"))
    clip = "a" * 32
    write_clip(clip, b"ID3-audio")
    client = TestClient(create_app(str(tmp_path / "test.sqlite3")))
    response = client.get(f"/api/audio/{clip}")
    assert response.status_code == 200
    assert response.content == b"ID3-audio"
    assert response.headers["content-type"] == "audio/mpeg"
    assert client.get(f"/api/audio/{'b' * 32}").status_code == 404
    # A malformed ID is answered exactly like an unknown one; no traversal is possible.
    assert client.get("/api/audio/not-a-clip-id").status_code == 404
    assert client.get("/api/audio/..%2F..%2Fetc%2Fpasswd").status_code == 404


def test_traces_route_exposes_the_recorded_steps_of_a_run(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNSENSE_MODE", "demo")
    path = str(tmp_path / "test.sqlite3")
    client = TestClient(create_app(path))
    run = client.post("/api/plan", json={"scenario": "calendar_retry"}).json()

    body = client.get("/api/traces", params={"run_id": run["run_id"]}).json()
    assert body["run_id"] == run["run_id"] and body["count"] == len(run["trace"])
    assert [t["tool"] for t in body["traces"]] == [t["tool"] for t in run["trace"]]
    first = body["traces"][0]
    assert first["step"] == 0 and first["retries"] == 0 and first["error"] is None
    assert first["output_json"] == {"status": run["trace"][0]["status"], "detail": run["trace"][0]["detail"]}
    assert first["created_at"]

    # Unfiltered is the cross-run view the per-run dashboard cannot show.
    second = client.post("/api/plan", json={}).json()
    everything = client.get("/api/traces").json()
    assert {t["run_id"] for t in everything["traces"]} == {run["run_id"], second["run_id"]}
    assert client.get("/api/traces", params={"run_id": "no-such-run"}).json()["count"] == 0
    assert client.get("/api/traces", params={"limit": 2}).json()["count"] == 2
    assert client.get("/api/traces", params={"limit": 0}).status_code == 422


def test_alerts_route_filters_by_session_and_tier(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNSENSE_MODE", "demo")
    path = str(tmp_path / "test.sqlite3")
    TypedStore(path).record_alert(obj_class="person", zone="center", distance_bucket="near",
                                  tier="danger", session_id="sess-1", latency_ms=12.5, spoken=True)
    TypedStore(path).record_alert(obj_class="pole", zone="left", distance_bucket="far", tier="notice")
    client = TestClient(create_app(path))

    everything = client.get("/api/alerts").json()
    assert everything["count"] == 2 and everything["session_id"] is None
    scoped = client.get("/api/alerts", params={"session_id": "sess-1"}).json()
    assert [a["obj_class"] for a in scoped["alerts"]] == ["person"]
    assert scoped["alerts"][0]["spoken"] is True and scoped["alerts"][0]["latency_ms"] == 12.5
    assert scoped["alerts"][0]["distance_bucket"] == "near" and scoped["alerts"][0]["ts"]
    by_tier = client.get("/api/alerts", params={"tier": "notice"}).json()
    assert by_tier["tier"] == "notice" and [a["obj_class"] for a in by_tier["alerts"]] == ["pole"]
    assert client.get("/api/alerts", params={"tier": "danger", "session_id": "sess-2"}).json()["count"] == 0


def test_history_routes_are_authenticated_in_live_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNSENSE_MODE", "live")
    monkeypatch.setenv("RUNSENSE_ADMIN_TOKEN", "test-secret")
    client = TestClient(create_app(str(tmp_path / "test.sqlite3")))
    assert client.get("/api/traces").status_code == 401
    assert client.get("/api/alerts").status_code == 401
    assert client.get("/api/traces", headers={"Authorization": "Bearer test-secret"}).status_code == 200


def test_bad_week_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNSENSE_MODE", "demo")
    client = TestClient(create_app(str(tmp_path / "test.sqlite3")))
    assert client.post("/api/plan", json={"week_start": "2026-09-15"}).status_code == 422


def test_session_change_request_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNSENSE_MODE", "demo")
    client = TestClient(create_app(str(tmp_path / "test.sqlite3")))
    response = client.post("/api/sessions/session-7/change-request", json={"request": "Move this to Saturday"})
    assert response.status_code == 200
    assert response.json()["status"] == "recorded"
    traces = client.get("/api/traces", params={"run_id": "session-7"}).json()["traces"]
    assert traces[0]["tool"] == "session.change_request"


def test_coach_ask_returns_honest_unconfigured_error(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    client = TestClient(create_app(str(tmp_path / "test.sqlite3")))
    response = client.post("/api/coach/ask", json={"question": "How hard should today be?"})
    assert response.status_code == 502
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]
