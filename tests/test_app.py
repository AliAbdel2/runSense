import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app
from app.db import SessionLocal
from app.models import Activity, Athlete, PlanWeek, Session
from app.services import plan_service as plan_service_module
from app.services.calendar_service import CalendarService, GoogleCalendarClient, GoogleCalendarInputError
from app.services.plan_service import PlanService
from app.services.strava_service import StravaClient, StravaService, normalize_activity


@pytest.fixture
def client(tmp_path):
    settings = Settings(runsense_api_key="test-key", database_url=f"sqlite:///{tmp_path / 'runsense.sqlite3'}")
    return TestClient(create_app(settings))


def auth(): return {"Authorization": "Bearer test-key"}


def test_plan_uses_app_service_and_persists_normalized_rows(client, tmp_path):
    week_start = date(2026, 9, 14)  # a Monday
    with SessionLocal() as db:
        db.add(Athlete(id="sara", name="Sara", guide_contacts=[], preferences={}))
        db.commit()
        for offset_days, km in ((21, 15.0), (14, 18.0), (7, 21.0)):
            db.add(Activity(id=f"seed-{offset_days}", athlete_id="sara", date=week_start - timedelta(days=offset_days), km=km))
        db.commit()

    response = client.post("/api/plan", json={"scenario": "guide_cancelled", "week_start": week_start.isoformat()})
    assert response.status_code == 200
    plan = response.json()

    # Baseline is the real trailing 3-week average of the seeded activities
    # (15 + 18 + 21) / 3 = 18.0 — not the old hardcoded 19.0.
    assert plan["baseline"] == {"km": 18.0, "source": "derived", "weeks_used": 3, "activity_count": 3}
    assert plan["baseline_km"] == 18.0
    assert plan["week_km"] == 18.0
    assert plan["validation"]["passed"] is True
    assert all(check["passed"] for check in plan["validation"]["checks"])
    assert plan["sessions"][1]["venue"] == "treadmill"

    with SessionLocal() as db:
        assert db.get(PlanWeek, plan["id"]) is not None
        rows = db.query(Session).filter(Session.plan_week_id == plan["id"]).all()
        assert len(rows) == 7


def test_plan_with_no_activity_history_uses_defaulted_baseline(client):
    week_start = date(2026, 9, 14)
    response = client.post("/api/plan", json={"scenario": "baseline", "week_start": week_start.isoformat()})
    assert response.status_code == 200
    plan = response.json()
    assert plan["baseline"]["source"] == "defaulted"
    assert plan["baseline"]["activity_count"] == 0
    assert plan["validation"]["passed"] is True


def test_invalid_plan_is_never_persisted_to_plan_weeks(client, monkeypatch):
    def always_fails(plan):
        return {"passed": False, "checks": [{"name": "weekly_volume_cap", "passed": False, "detail": "forced failure for the test"}]}

    monkeypatch.setattr(plan_service_module, "validate_plan", always_fails)

    with SessionLocal() as db:
        before = db.query(PlanWeek).count()
        with pytest.raises(ValueError, match="failed validation"):
            PlanService(db).create(week_start=date(2026, 9, 14))
        assert db.query(PlanWeek).count() == before


def test_live_session_persists_aggregate_and_exports_tcx(client):
    started = datetime(2026, 9, 13, 8, tzinfo=timezone.utc)
    response = client.post("/v1/sessions", headers=auth(), json={"started_at": started.isoformat()})
    assert response.status_code == 201
    session_id = response.json()["session_id"]
    samples = [{"timestamp": (started + timedelta(seconds=i * 5)).isoformat(), "latitude": 0, "longitude": i * .0001, "accuracy_m": 5} for i in range(3)]
    assert client.post(f"/v1/sessions/{session_id}/samples", headers=auth(), json={"samples": samples}).status_code == 200
    finished = client.post(f"/v1/sessions/{session_id}/finish", headers=auth(), json={"at": (started + timedelta(seconds=12)).isoformat()})
    assert finished.status_code == 200 and finished.json()["state"] == "finished"
    assert client.get(f"/v1/sessions/{session_id}/export.tcx", headers=auth()).content.startswith(b"<?xml")


def test_provider_routes_require_api_key(client):
    assert client.get("/v1/tools").status_code == 401


def test_strava_normalization_excludes_coordinates():
    normalized = normalize_activity({"id": 1, "sport_type": "Run", "start_date": "2026-09-13T07:00:00Z", "distance": 5000, "average_speed": 2.7777778, "map": {"polyline": "private"}})
    assert normalized["distance_km"] == 5.0 and "map" not in normalized and normalized["pace_min_per_km"] == 6.0


def test_calendar_confirmation_gate_prevents_provider_call():
    calls = []
    async def operation():
        transport = httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200, json={}))
        async with GoogleCalendarClient("token", transport=transport) as client:
            await CalendarService(client).create_session(title="Run", start=datetime(2026, 9, 15, 9, tzinfo=timezone.utc), end=datetime(2026, 9, 15, 10, tzinfo=timezone.utc), time_zone="UTC", idempotency_key="sara-run-1", owner_confirmed=False, session_type="run", venue_type="treadmill")
    with pytest.raises(GoogleCalendarInputError, match="explicit confirmation"):
        import asyncio; asyncio.run(operation())
    assert calls == []
