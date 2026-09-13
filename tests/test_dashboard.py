"""The Streamlit dashboard's data layer, exercised without Streamlit running.

``dashboard/app.py`` is layout only; every query it makes lives in
``dashboard/data.py`` so it can be tested here against a real SQLite file. The
page itself is never rendered in this suite - a headless render would prove
nothing about how it reads.
"""

import asyncio

import pytest

from dashboard import data
from runsense.agent import Agent
from runsense.db import TypedStore
from runsense.models import PlanRequest
from runsense.store import Store
from test_planner import WEEK


@pytest.fixture
def populated(tmp_path):
    """One real agent run plus two alerts, in one database file."""
    path = str(tmp_path / "typed.sqlite3")
    run = asyncio.run(Agent(Store(path)).plan(PlanRequest(week_start=WEEK)))
    store = TypedStore(path)
    store.record_alert(obj_class="person", zone="center", distance_bucket="near", tier="danger",
                       session_id="sess-1", latency_ms=18.0, spoken=True)
    store.record_alert(obj_class="pole", zone="left", distance_bucket="far", tier="notice",
                       session_id="sess-2")
    return path, run


def test_database_path_prefers_the_configured_file(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNSENSE_DB", str(tmp_path / "from-env.sqlite3"))
    assert data.database_path() == str(tmp_path / "from-env.sqlite3")
    assert data.database_path("explicit.sqlite3") == "explicit.sqlite3"


def test_recent_traces_reads_a_real_run(populated):
    path, run = populated
    rows = data.recent_traces(path=path)
    assert [row["tool"] for row in rows] == [t["tool"] for t in run["trace"]]
    assert all(row["run_id"] == run["run_id"] for row in rows)
    # JSON-safe throughout, so the same shape serves the API and the page.
    assert isinstance(rows[0]["created_at"], str)
    assert data.recent_traces(run["run_id"], path=path) == rows
    assert data.recent_traces("no-such-run", path=path) == []


def test_recent_traces_returns_the_newest_rows_when_limited(populated):
    path, run = populated
    assert data.recent_traces(limit=3, path=path) == data.recent_traces(path=path)[-3:]
    assert data.recent_traces(limit=0, path=path) == []


def test_recent_alerts_filters_by_session_and_tier(populated):
    path, _ = populated
    assert [a["obj_class"] for a in data.recent_alerts(path=path)] == ["person", "pole"]
    assert [a["obj_class"] for a in data.recent_alerts("sess-1", path=path)] == ["person"]
    assert [a["obj_class"] for a in data.recent_alerts(tier="notice", path=path)] == ["pole"]
    assert data.recent_alerts("sess-1", "notice", path=path) == []
    alert = data.recent_alerts("sess-1", path=path)[0]
    assert (alert["zone"], alert["distance_bucket"], alert["spoken"]) == ("center", "near", True)
    assert isinstance(alert["ts"], str)


def test_run_ids_and_tiers_feed_the_page_filters(tmp_path):
    path = str(tmp_path / "typed.sqlite3")
    agent = Agent(Store(path))
    first = asyncio.run(agent.plan(PlanRequest(week_start=WEEK)))
    second = asyncio.run(agent.plan(PlanRequest(week_start=WEEK)))
    assert data.run_ids(path=path) == [second["run_id"], first["run_id"]]

    store = TypedStore(path)
    store.record_alert(obj_class="pole", zone="left", distance_bucket="far", tier="notice")
    store.record_alert(obj_class="person", zone="center", distance_bucket="near", tier="danger")
    assert data.tiers(path=path) == ["danger", "notice"]


def test_empty_database_reads_cleanly(tmp_path):
    path = str(tmp_path / "empty.sqlite3")
    assert data.recent_traces(path=path) == []
    assert data.recent_alerts(path=path) == []
    assert data.run_ids(path=path) == [] and data.tiers(path=path) == []


def test_evaluation_report_is_the_harness_report(monkeypatch):
    async def fake_evaluate():
        return {"passed": 2, "total": 2, "results": [], "scope": "synthetic",
                "perception": {"status": "triage_logic_tested"}}

    monkeypatch.setattr("runsense.evaluation.evaluate", fake_evaluate)
    report = data.evaluation_report()
    assert report["passed"] == report["total"] == 2
    # The perception section stays a separate, differently-labelled key.
    assert report["perception"]["status"] == "triage_logic_tested"


def test_the_page_module_imports_and_only_defines_layout():
    # Streamlit is the optional `dashboard` extra; the data layer above needs none of it.
    pytest.importorskip("streamlit")
    from dashboard import app

    assert callable(app.main)
    assert app.data is data
