import asyncio
import json
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from runsense.agent import Agent
from runsense.main import create_app
from runsense.models import PlanRequest
from runsense.store import Store
from runsense.strava_mcp import StravaMCPError
from runsense.strava_source import StravaConfig, StravaSource, StravaSourceError, normalize_activities

WEEK = date(2026, 9, 14)


def row(identity=1, distance=5000, sport="Run", day="2026-09-10T08:00:00"):
    return {"id": identity, "start_date_local": day, "distance": distance, "sport_type": sport}


def result(rows=None, **extra):
    return {"structuredContent": {"activities": rows if rows is not None else [row()], **extra}}


def test_mapping_converts_units_filters_sports_dates_and_deduplicates():
    rows = [row(), row(), row(2, 25000, "Ride"), row(3, 7000, "TrailRun"),
            row(4, 9000, day="2026-08-01"), row(5, 5000, day="2026-09-14")]
    history = normalize_activities(result(rows), StravaConfig(), WEEK)
    assert [a.km for a in history] == [5, 7]
    assert all(a.source == "strava_mcp" for a in history)


def test_explicit_mapping_accepts_json_text_without_inventing_fields():
    config = StravaConfig(rows_pointer="/data/runs", date_field="day", distance_field="km", distance_unit="kilometers",
                          sport_field="sport", id_field="key")
    payload = {"content": [{"type": "text", "text": json.dumps({"data": {"runs": [
        {"key": "a", "day": "2026-09-12", "km": 4.5, "sport": "Run"}]}})}]}
    assert normalize_activities(payload, config, WEEK)[0].km == 4.5


@pytest.mark.parametrize("payload", [
    result([row(distance=float("nan"))]), result([row(distance=-1)]), result([row(distance=True)]),
    result([row(day="not-a-date")]), result([row(), row(distance=9999)]),
    result([{"text": "I ran five kilometres"}]), result([], has_more=True),
    {"content": [{"type": "text", "text": "Your running looks good."}]},
    {"isError": True, "content": [{"text": "secret-detail"}]},
])
def test_unusable_or_ambiguous_history_is_rejected(payload):
    with pytest.raises(StravaSourceError) as error:
        normalize_activities(payload, StravaConfig(), WEEK)
    assert "secret-detail" not in str(error.value)


def test_arguments_expand_typed_dates_without_interpolating_other_text():
    config = StravaConfig(arguments_json='{"after":"${after_epoch}","before":"${before_date}"}')
    args = config.arguments(WEEK)
    assert isinstance(args["after"], int)
    assert args["before"] == "2026-09-14"
    with pytest.raises(StravaSourceError):
        StravaConfig(arguments_json='{"x":"text${before_date}"}').arguments(WEEK)


class FakeMCP:
    calls = []
    error = False
    tools = [{"name": "read_runs", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}]

    def __init__(self, token):
        assert token in ("private-token", "new-private-token")
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def initialize(self):
        if self.error:
            raise StravaMCPError("access token was rejected", status_code=401)
        return {}
    async def list_tools(self):
        return self.tools
    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return result([row(1, 15000, day="2026-08-25"), row(2, 18000, day="2026-09-01"), row(3, 21000)])


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setenv("STRAVA_MCP_ACCESS_TOKEN", "private-token")
    monkeypatch.setenv("STRAVA_MCP_ACTIVITY_TOOL", "read_runs")
    monkeypatch.setenv("RUNSENSE_MODE", "demo")
    FakeMCP.calls, FakeMCP.error = [], False
    yield StravaSource(client_factory=FakeMCP)
    FakeMCP.error = False


def test_discovery_claims_only_handshake_not_activity_access(source):
    status = asyncio.run(source.check())
    assert status["status"] == "connected" and status["tool_configured"]
    assert not FakeMCP.calls
    assert "eligibility" in status["detail"]
    assert "private-token" not in json.dumps(status)


def test_personal_mcp_plan_is_grounded_and_never_persisted(source, tmp_path):
    store = Store(str(tmp_path / "personal.sqlite3"))
    agent = Agent(store, strava_source=source)
    preview = asyncio.run(agent.plan(PlanRequest(source="strava_mcp", week_start=WEEK)))
    assert preview["mode"] == "strava_preview" and preview["retention"] == "memory_only"
    assert preview["plan"]["athlete_name"] == "You"
    assert preview["plan"]["baseline_km"] == 18
    assert preview["plan"]["week_km"] == 18
    assert all(s["venue"] in ("home", "treadmill") for s in preview["plan"]["sessions"])
    assert store.get_run(preview["run_id"]) is None
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM actions").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    assert source.get_preview(preview["run_id"]) == preview
    with pytest.raises(StravaSourceError, match="cannot be exported"):
        asyncio.run(agent.commit(preview["run_id"]))


def test_expiry_disconnect_and_auth_failure_clear_personal_previews(source):
    now = [100.0]
    source.clock = lambda: now[0]
    source.save_preview({"run_id": "first", "private": "data"})
    now[0] += 3601
    assert source.get_preview("first") is None
    source.save_preview({"run_id": "second"})
    FakeMCP.error = True
    assert asyncio.run(source.check())["status"] == "access_denied"
    assert source.get_preview("second") is None
    source.save_preview({"run_id": "third"})
    assert source.disconnect()["status"] == "not_connected"
    assert source.get_preview("third") is None
    assert not source.status()["configured"]


def test_rotating_token_reconnects_after_local_disconnect(source, monkeypatch):
    assert source.disconnect()["status"] == "not_connected"
    monkeypatch.setenv("STRAVA_MCP_ACCESS_TOKEN", "new-private-token")
    status = asyncio.run(source.check())
    assert status["status"] == "connected"
    assert status["configured"] is True


def test_activity_tool_requires_explicit_read_only_annotation(source, monkeypatch):
    monkeypatch.setattr(FakeMCP, "tools", [{"name": "read_runs", "inputSchema": {"type": "object"}, "annotations": {}}])
    status = asyncio.run(source.check())
    assert status["status"] == "connected"
    assert status["tool_configured"] is False
    with pytest.raises(StravaSourceError, match="not read-only"):
        asyncio.run(source.get_activities(WEEK, []))


def test_activity_tool_rejects_destructive_annotation(source, monkeypatch):
    monkeypatch.setattr(FakeMCP, "tools", [{"name": "read_runs", "inputSchema": {"type": "object"},
                                             "annotations": {"readOnlyHint": True, "destructiveHint": True}}])
    assert asyncio.run(source.check())["tool_configured"] is False
    with pytest.raises(StravaSourceError, match="not read-only"):
        asyncio.run(source.get_activities(WEEK, []))


def test_missing_credentials_do_not_call_mcp_or_silently_use_fixtures(monkeypatch, tmp_path):
    monkeypatch.delenv("STRAVA_MCP_ACCESS_TOKEN", raising=False)
    source = StravaSource(client_factory=lambda token: pytest.fail("must not connect"))
    assert asyncio.run(source.check())["status"] == "not_connected"
    agent = Agent(Store(str(tmp_path / "missing.sqlite3")), source)
    with pytest.raises(StravaSourceError, match="not connected"):
        asyncio.run(agent.plan(PlanRequest(source="strava_mcp", week_start=WEEK)))


def test_personal_routes_need_session_and_replay_expires(source, tmp_path):
    app = create_app(str(tmp_path / "api.sqlite3"))
    app.state.agent.strava = source
    client = TestClient(app)
    assert client.post("/api/strava/check").status_code == 401
    assert client.post("/api/plan", json={"source": "strava_mcp"}).status_code == 401
    assert client.get("/").status_code == 200
    assert client.post("/api/strava/check").json()["status"] == "connected"
    preview = client.post("/api/plan", json={"source": "strava_mcp", "week_start": WEEK.isoformat()}).json()
    assert client.get(f"/api/runs/{preview['run_id']}").json() == preview
    outsider = TestClient(app)
    assert outsider.get(f"/api/runs/{preview['run_id']}").status_code == 401
    assert client.post("/api/strava/disconnect").json()["status"] == "not_connected"
    assert client.get(f"/api/runs/{preview['run_id']}").status_code == 404


def test_synthetic_cancellation_rejected_for_personal_source(source, tmp_path):
    agent = Agent(Store(str(tmp_path / "api.sqlite3")), source)
    with pytest.raises(StravaSourceError, match="Synthetic scenarios"):
        asyncio.run(agent.plan(PlanRequest(source="strava_mcp", scenario="guide_cancelled", week_start=WEEK)))
    assert not FakeMCP.calls


def test_unusable_activity_response_updates_status_and_purges_preview(source, monkeypatch):
    asyncio.run(source.check())
    source.save_preview({"run_id": "prior"})
    async def malformed(self, name, arguments):
        return result([row(day="bad-date")])
    monkeypatch.setattr(FakeMCP, "call_tool", malformed)
    with pytest.raises(StravaSourceError):
        asyncio.run(source.get_activities(WEEK, []))
    assert source.status()["status"] == "error"
    assert source.get_preview("prior") is None
