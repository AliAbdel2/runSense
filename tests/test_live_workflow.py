import asyncio
import copy
from dataclasses import replace
from datetime import timedelta

import pytest

from runsense import db, delivery, integrations, observability
from runsense.agent import Agent
from runsense.models import PlanRequest
from runsense.planner import demo_history
from runsense.store import Store
from test_planner import WEEK


def fake_providers(monkeypatch):
    rows = [dict(a.model_dump(mode="json"), source="athlete_authored") for a in demo_history(WEEK)]
    events = {}
    pages = {}
    controls = {"wrong_notion_readback": False}

    class Context:
        def __init__(self, settings):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass

    class Sheets(Context):
        async def get_activities(self):
            return copy.deepcopy(rows)

    class Calendar(Context):
        async def upsert_session(self, session):
            events[session["id"]] = integrations._calendar_event(session, session["id"])
            return events[session["id"]]
        async def get_session(self, event_id):
            return events[event_id]

    class Notion(Context):
        async def upsert_plan(self, plan):
            pages[plan["id"]] = {"id": plan["id"], "properties": integrations._notion_properties(integrations.Settings(), plan)}
            return pages[plan["id"]]
        async def get_plan(self, page_id):
            page = copy.deepcopy(pages[page_id])
            if controls["wrong_notion_readback"]:
                page["properties"]["Plan ID"]["rich_text"][0]["text"]["content"] = "wrong"
            return page

    monkeypatch.setattr(integrations, "SheetsClient", Sheets)
    monkeypatch.setattr(integrations, "CalendarClient", Calendar)
    monkeypatch.setattr(integrations, "NotionClient", Notion)
    monkeypatch.setenv("GOOGLE_ACCESS_TOKEN", "fake-token")
    monkeypatch.setenv("NOTION_API_KEY", "fake-token")
    monkeypatch.setenv("NOTION_DATA_SOURCE_ID", "fake-source")
    return rows, events, pages, controls


def test_preview_then_commit_and_repeat_are_idempotent(tmp_path, monkeypatch):
    rows, events, pages, controls = fake_providers(monkeypatch)
    agent = Agent(Store(str(tmp_path / "test.sqlite3")))

    async def run():
        preview = await agent.plan(PlanRequest(week_start=WEEK), live=True)
        assert not events and not pages
        assert all(s["venue"] in ("home", "treadmill") for s in preview["plan"]["sessions"])
        first = await agent.commit(preview["run_id"])
        second = await agent.commit(preview["run_id"])
        assert first == second and first["committed"]
        assert len(events) == 4 and len(pages) == 1
    asyncio.run(run())


def test_changed_source_blocks_commit_before_writes(tmp_path, monkeypatch):
    rows, events, pages, controls = fake_providers(monkeypatch)
    agent = Agent(Store(str(tmp_path / "test.sqlite3")))

    async def run():
        preview = await agent.plan(PlanRequest(week_start=WEEK), live=True)
        rows[0]["km"] += 1
        with pytest.raises(ValueError, match="training log changed"):
            await agent.commit(preview["run_id"])
        assert not events and not pages
    asyncio.run(run())


def test_superseded_preview_cannot_overwrite_new_plan(tmp_path, monkeypatch):
    fake_providers(monkeypatch)
    agent = Agent(Store(str(tmp_path / "test.sqlite3")))

    async def run():
        old = await agent.plan(PlanRequest(week_start=WEEK), live=True)
        await agent.plan(PlanRequest(week_start=WEEK), live=True)
        with pytest.raises(ValueError, match="superseded"):
            await agent.commit(old["run_id"])
    asyncio.run(run())


def _sms_trace(result):
    return next(t for t in result["trace"] if t["tool"] == "sms.notify_guide_change")


def test_guide_cancellation_sends_one_reschedule_sms(tmp_path, monkeypatch):
    sent = []

    async def fake_send(to, text):
        sent.append((to, text))
        return "queued:SM3"

    monkeypatch.setenv("RUNSENSE_GUIDE_PHONE", "+15551234567")
    monkeypatch.setattr(delivery, "send_sms_notice", fake_send)
    agent = Agent(Store(str(tmp_path / "test.sqlite3")))
    result = asyncio.run(agent.plan(PlanRequest(week_start=WEEK, scenario="guide_cancelled")))

    assert result["validation"]["passed"]
    assert len(sent) == 1
    to, text = sent[0]
    assert to == "+15551234567"
    # The notice names the affected day and states the adaptation that was made.
    assert (WEEK + timedelta(days=1)).isoformat() in text and "treadmill" in text
    trace = _sms_trace(result)
    assert trace["status"] == "completed" and "queued:SM3" in trace["detail"]


def test_guide_cancellation_without_sms_configured_still_adapts(tmp_path, monkeypatch):
    monkeypatch.delenv("RUNSENSE_GUIDE_PHONE", raising=False)

    async def unreachable(to, text):
        raise AssertionError("no SMS should be attempted without a configured contact")

    monkeypatch.setattr(delivery, "send_sms_notice", unreachable)
    agent = Agent(Store(str(tmp_path / "test.sqlite3")))
    result = asyncio.run(agent.plan(PlanRequest(week_start=WEEK, scenario="guide_cancelled")))

    assert result["validation"]["passed"]
    tuesday = result["plan"]["sessions"][1]
    assert tuesday["venue"] == "treadmill" and tuesday["guide_status"] == "declined"
    trace = _sms_trace(result)
    assert trace["status"] == "skipped" and "RUNSENSE_GUIDE_PHONE" in trace["detail"]


def test_guide_cancellation_survives_a_failed_sms(tmp_path, monkeypatch):
    async def failing(to, text):
        return "sms_failed"

    monkeypatch.setenv("RUNSENSE_GUIDE_PHONE", "+15551234567")
    monkeypatch.setattr(delivery, "send_sms_notice", failing)
    agent = Agent(Store(str(tmp_path / "test.sqlite3")))
    result = asyncio.run(agent.plan(PlanRequest(week_start=WEEK, scenario="guide_cancelled")))

    assert result["validation"]["passed"] and len(result["calendar_events"]) == 4
    trace = _sms_trace(result)
    assert trace["status"] == "skipped" and "notify the guide manually" in trace["detail"]
    # The honest trace survives a restart alongside the rest of the run.
    assert _sms_trace(agent.store.get_run(result["run_id"]))["detail"] == trace["detail"]


def test_baseline_scenario_never_sends_an_sms(tmp_path, monkeypatch):
    async def unreachable(to, text):
        raise AssertionError("only a cancelled guide triggers a notification")

    monkeypatch.setenv("RUNSENSE_GUIDE_PHONE", "+15551234567")
    monkeypatch.setattr(delivery, "send_sms_notice", unreachable)
    agent = Agent(Store(str(tmp_path / "test.sqlite3")))
    result = asyncio.run(agent.plan(PlanRequest(week_start=WEEK)))
    assert not [t for t in result["trace"] if t["tool"] == "sms.notify_guide_change"]


def test_demo_run_mirrors_its_trace_into_the_typed_table(tmp_path):
    path = str(tmp_path / "test.sqlite3")
    agent = Agent(Store(path))
    result = asyncio.run(agent.plan(PlanRequest(week_start=WEEK, scenario="calendar_retry")))

    rows = db.TypedStore(path).list_tool_traces(result["run_id"])
    # One row per in-memory step, in order, with the list index as the step number.
    assert [row.tool for row in rows] == [t["tool"] for t in result["trace"]]
    assert [row.step for row in rows] == list(range(len(result["trace"])))
    assert all(row.run_id == result["run_id"] for row in rows)

    retried = next(t for t in result["trace"] if t["status"] == "retrying")
    stored = rows[result["trace"].index(retried)]
    assert stored.output_json == {"status": "retrying", "detail": retried["detail"]}
    assert stored.latency_ms == retried["latency_ms"]
    assert stored.error is None  # a step that recovered is not an error
    # attempt -> retries: the first attempt is zero retries, and the raw attempt
    # number is kept on input_json so the mapping stays reversible.
    assert stored.retries == retried["attempt"] - 1
    assert stored.input_json == {"attempt": retried["attempt"]}
    # The injected 503: a "retrying" step at attempt 1, then the write that
    # succeeded on attempt 2, then three untroubled sessions.
    assert [row.retries for row in rows if row.tool == "calendar.upsert_session"] == [0, 1, 0, 0, 0]

    # The in-memory shape the API, app.js and evaluation.py read is untouched.
    assert all(set(t) == {"tool", "status", "attempt", "latency_ms", "detail"} for t in result["trace"])


def test_typed_trace_rows_are_not_duplicated_by_a_second_run(tmp_path):
    path = str(tmp_path / "test.sqlite3")
    agent = Agent(Store(path))
    first = asyncio.run(agent.plan(PlanRequest(week_start=WEEK)))
    second = asyncio.run(agent.plan(PlanRequest(week_start=WEEK)))
    store = db.TypedStore(path)
    assert len(store.list_tool_traces(first["run_id"])) == len(first["trace"])
    assert len(store.list_tool_traces()) == len(first["trace"]) + len(second["trace"])


def test_commit_appends_its_own_steps_without_rewriting_the_planning_ones(tmp_path, monkeypatch):
    fake_providers(monkeypatch)
    path = str(tmp_path / "test.sqlite3")
    agent = Agent(Store(path))

    async def run():
        preview = await agent.plan(PlanRequest(week_start=WEEK), live=True)
        planned = len(preview["trace"])
        committed = await agent.commit(preview["run_id"])
        rows = db.TypedStore(path).list_tool_traces(preview["run_id"])
        assert [row.tool for row in rows] == [t["tool"] for t in committed["trace"]]
        assert [row.step for row in rows] == list(range(len(committed["trace"])))
        assert len(rows) > planned  # the commit's own verified writes were appended
        # Committing again is a no-op for the run, so it adds no further rows.
        await agent.commit(preview["run_id"])
        assert len(db.TypedStore(path).list_tool_traces(preview["run_id"])) == len(rows)
    asyncio.run(run())


def test_a_failing_typed_store_never_breaks_a_run(tmp_path, monkeypatch):
    """The non-fatal guarantee: recording is optional infrastructure, the run is not."""
    calls = []

    def exploding(session, **kwargs):
        calls.append(kwargs["tool"])
        raise RuntimeError("database is locked")

    monkeypatch.setattr(observability, "record_tool_trace", exploding)
    path = str(tmp_path / "test.sqlite3")
    agent = Agent(Store(path))
    result = asyncio.run(agent.plan(PlanRequest(week_start=WEEK, scenario="calendar_retry")))

    assert calls  # the write really was attempted, and really did raise
    # The run itself is untouched: validation, simulated events, in-memory trace
    # and the durable blob row all land exactly as they do without the typed table.
    assert result["validation"]["passed"] and len(result["calendar_events"]) == 4
    assert any(t["status"] == "retrying" for t in result["trace"])
    assert agent.store.get_run(result["run_id"])["trace"] == result["trace"]
    assert db.TypedStore(path).list_tool_traces(result["run_id"]) == []


def test_a_failing_typed_store_never_breaks_a_commit(tmp_path, monkeypatch):
    rows, events, pages, controls = fake_providers(monkeypatch)

    def exploding(path=None):
        raise RuntimeError("no such table: tool_traces")

    monkeypatch.setattr(observability, "_typed_store", exploding)
    agent = Agent(Store(str(tmp_path / "test.sqlite3")))

    async def run():
        preview = await agent.plan(PlanRequest(week_start=WEEK), live=True)
        committed = await agent.commit(preview["run_id"])
        assert committed["committed"]
        assert len(events) == 4 and len(pages) == 1
    asyncio.run(run())


def test_notion_readback_failure_persists_partial_trace_then_retry_reconciles(tmp_path, monkeypatch):
    rows, events, pages, controls = fake_providers(monkeypatch)
    agent = Agent(Store(str(tmp_path / "test.sqlite3")))

    async def run():
        preview = await agent.plan(PlanRequest(week_start=WEEK), live=True)
        controls["wrong_notion_readback"] = True
        with pytest.raises(ValueError, match="Notion read-back"):
            await agent.commit(preview["run_id"])
        saved = agent.store.get_run(preview["run_id"])
        assert not saved["committed"] and saved["trace"][-1]["status"] == "failed"
        controls["wrong_notion_readback"] = False
        assert (await agent.commit(preview["run_id"]))["committed"]
        assert len(events) == 4 and len(pages) == 1
    asyncio.run(run())

