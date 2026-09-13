import asyncio
import json

import httpx
import pytest

from runsense.llm import propose_with_claude
from runsense.planner import demo_history, generate_plan, guide_confirmations
from test_planner import WEEK


def test_model_must_read_inputs_and_repair_invalid_proposal(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")
    history, guides = demo_history(WEEK), guide_confirmations(WEEK, "baseline")
    valid = generate_plan(history, WEEK, guides=guides).model_dump(mode="json")
    invalid = {**valid, "athlete_name": "Mallory"}
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        index = len(calls)
        if index == 1:
            blocks = [{"type": "tool_use", "id": "read1", "name": "read_training_history", "input": {}},
                      {"type": "tool_use", "id": "read2", "name": "read_constraints", "input": {}}]
        else:
            blocks = [{"type": "tool_use", "id": f"p{index}", "name": "propose_week", "input": invalid if index == 2 else valid}]
        return httpx.Response(200, json={"content": blocks})

    trace = []
    plan = asyncio.run(propose_with_claude(history, WEEK, "baseline", guides, trace, transport=httpx.MockTransport(handler)))
    assert plan.athlete_name == "Sara"
    assert len(calls) == 3
    assert calls[2]["messages"][-1]["content"][0]["is_error"] is True
    assert {t["name"] for t in calls[0]["tools"]} == {"read_training_history", "read_constraints", "propose_week"}


def test_model_tool_budget_is_bounded(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"content": [{"type": "tool_use", "id": str(len(calls)), "name": "send_email", "input": {}}]})

    with pytest.raises(ValueError, match="six-step"):
        asyncio.run(propose_with_claude(demo_history(WEEK), WEEK, "baseline", {}, [], httpx.MockTransport(handler)))
    assert len(calls) == 6


def test_missing_model_credentials_does_not_fallback_as_ai(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        asyncio.run(propose_with_claude(demo_history(WEEK), WEEK, "baseline", {}, []))

