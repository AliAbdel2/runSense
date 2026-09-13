import asyncio

from fastapi.testclient import TestClient

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


def test_status_does_not_claim_connected_when_only_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "never-output-this")
    client = TestClient(create_app(str(tmp_path / "test.sqlite3")))
    response = client.get("/api/status")
    assert "never-output-this" not in response.text
    assert response.json()["integrations"][1]["status"] == "configured_unverified"


def test_bad_week_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNSENSE_MODE", "demo")
    client = TestClient(create_app(str(tmp_path / "test.sqlite3")))
    assert client.post("/api/plan", json={"week_start": "2026-09-15"}).status_code == 422

