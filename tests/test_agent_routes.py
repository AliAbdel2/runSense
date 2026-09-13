"""Agent tool-calling: db persistence, plan tool, and the corrected chat path.

Never calls real Anthropic or real Strava — ChatAnthropic is replaced with a
scripted stub, and StravaClient.list_activities is monkeypatched to return
canned data instead of making an HTTP request.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.agents.coach_agent as coach_agent
import app.services.plan_service as plan_service_module
from app.config.settings import Settings
from app.db import Base
from app.main import create_app
from app.models import Activity
from app.services.plan_service import PlanService, build_plan_tools
from app.services.strava_service import ProviderResponse, StravaClient


def auth():
    return {"Authorization": "Bearer test-key"}


@pytest.fixture
def agent_client(tmp_path):
    settings = Settings(
        runsense_api_key="test-key",
        database_url=f"sqlite:///{tmp_path / 'agent.sqlite3'}",
        anthropic_api_key="test-anthropic-key",
        anthropic_model="test-model",
        strava_access_token="test-strava-token",
    )
    return TestClient(create_app(settings))


class FakeAIMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


def fake_chat_anthropic(responses):
    """A ChatAnthropic stand-in: bind_tools() is a no-op, ainvoke() pops the
    next scripted reply off `responses` in order."""
    class FakeChatAnthropic:
        def __init__(self, *args, **kwargs):
            pass

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            return responses.pop(0)

    return FakeChatAnthropic


def _db_session(tmp_path, name="plan_tools.sqlite3"):
    engine = create_engine(f"sqlite:///{tmp_path / name}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)()


# --- PART 3/4a: the corrected path + auth --------------------------------

def test_agent_chat_requires_api_key(agent_client):
    response = agent_client.post("/v1/agent/chat", json={"question": "hi"})
    assert response.status_code == 401


def test_agent_chat_reachable_at_corrected_path(agent_client, monkeypatch):
    monkeypatch.setattr(coach_agent, "ChatAnthropic", fake_chat_anthropic([FakeAIMessage(content="Hello!")]))
    response = agent_client.post("/v1/agent/chat", headers=auth(), json={"question": "hi"})
    assert response.status_code == 200
    assert response.json()["answer"] == "Hello!"


# --- PART 1: the db=None regression test ---------------------------------

def test_strava_tool_call_persists_activity_rows(agent_client, monkeypatch, tmp_path):
    async def fake_list_activities(self, **kwargs):
        return ProviderResponse(
            data=[{
                "id": 555, "sport_type": "Run", "start_date": "2026-09-01T07:00:00Z",
                "distance": 5000, "average_speed": 2.7777778,
                "average_heartrate": None, "total_elevation_gain": 12.0,
            }],
            status_code=200, rate_limits={},
        )
    monkeypatch.setattr(StravaClient, "list_activities", fake_list_activities)

    responses = [
        FakeAIMessage(tool_calls=[{"name": "strava_get_training_history", "args": {"weeks": 4}, "id": "call-1"}]),
        FakeAIMessage(content="Synced your recent runs."),
    ]
    monkeypatch.setattr(coach_agent, "ChatAnthropic", fake_chat_anthropic(responses))

    response = agent_client.post("/v1/agent/chat", headers=auth(), json={"question": "sync my strava activities"})
    assert response.status_code == 200
    assert response.json()["tool_calls"][0]["status"] == "success"

    from app.db import SessionLocal
    with SessionLocal() as db:
        rows = db.query(Activity).filter(Activity.athlete_id == "sara").all()
        assert len(rows) == 1
        assert rows[0].strava_id == "555"
        assert rows[0].km == 5.0
        assert rows[0].avg_hr is None  # HR was null in the source data — never assumed


# --- PART 2: the plan tool -------------------------------------------------

def test_plan_tool_returns_plan_and_validation_evidence(tmp_path):
    db = _db_session(tmp_path)
    tool = build_plan_tools(PlanService(db))[0]

    result = asyncio.run(tool.ainvoke({"scenario": "baseline", "week_start": "2026-09-14"}))

    assert result["baseline"]["source"] == "defaulted"  # no seeded activities
    assert result["validation"]["passed"] is True
    assert {c["name"] for c in result["validation"]["checks"]} == {
        "weekly_volume_cap", "hard_day_spacing", "guide_requirement", "spoken_summary_length",
    }
    db.close()


def test_plan_tool_surfaces_violations_without_raising(tmp_path, monkeypatch):
    def always_fails(plan):
        return {"passed": False, "checks": [{"name": "weekly_volume_cap", "passed": False, "detail": "forced failure"}]}
    monkeypatch.setattr(plan_service_module, "validate_plan", always_fails)

    db = _db_session(tmp_path)
    tool = build_plan_tools(PlanService(db))[0]

    result = asyncio.run(tool.ainvoke({"scenario": "baseline", "week_start": "2026-09-14"}))

    assert result["created"] is False
    assert result["validation"]["passed"] is False
    assert result["validation"]["checks"][0]["name"] == "weekly_volume_cap"
    db.close()


def test_agent_loop_survives_a_failing_plan_tool_call(agent_client, monkeypatch):
    def always_fails(plan):
        return {"passed": False, "checks": [{"name": "weekly_volume_cap", "passed": False, "detail": "forced failure"}]}
    monkeypatch.setattr(plan_service_module, "validate_plan", always_fails)

    responses = [
        FakeAIMessage(tool_calls=[{"name": "plan_create_week", "args": {"scenario": "baseline", "week_start": "2026-09-14"}, "id": "call-1"}]),
        FakeAIMessage(content="Your plan didn't pass validation, here's why."),
    ]
    monkeypatch.setattr(coach_agent, "ChatAnthropic", fake_chat_anthropic(responses))

    response = agent_client.post("/v1/agent/chat", headers=auth(), json={"question": "make me a plan"})

    assert response.status_code == 200  # not a 500 — the loop survived the failure
    body = response.json()
    assert body["tool_calls"][0]["status"] == "success"  # the tool call itself didn't error
    assert body["answer"] == "Your plan didn't pass validation, here's why."
