import asyncio
import copy
from dataclasses import replace

import pytest

from runsense import integrations
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

