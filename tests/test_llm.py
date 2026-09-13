import asyncio
import json
import re

import httpx
import pytest

from runsense import delivery, llm
from runsense.integrations import Settings
from runsense.llm import EXTENDED_TOOLS, propose_with_claude
from runsense.planner import demo_history, generate_plan, guide_confirmations
from test_planner import WEEK


def reply(blocks):
    """A complete Anthropic Messages response so the SDK parses it exactly as it would live."""
    return httpx.Response(200, json={
        "id": "msg_test", "type": "message", "role": "assistant", "model": "test-model",
        "stop_reason": "tool_use", "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1}, "content": blocks})


def use(call_id, name, payload):
    return {"type": "tool_use", "id": call_id, "name": name, "input": payload}


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
            blocks = [use("read1", "read_training_history", {}), use("read2", "read_constraints", {})]
        else:
            blocks = [use(f"p{index}", "propose_week", invalid if index == 2 else valid)]
        return reply(blocks)

    trace = []
    plan = asyncio.run(propose_with_claude(history, WEEK, "baseline", guides, trace,
                                           transport=httpx.MockTransport(handler)))
    assert plan.athlete_name == "Sara"
    assert len(calls) == 3
    # The rejected proposal comes back as a retryable error tool result, not an exception.
    assert calls[2]["messages"][-1]["content"][0]["is_error"] is True
    assert "Mallory" not in json.dumps(calls[2]["messages"][-1])
    assert {t["name"] for t in calls[0]["tools"]} == {"read_training_history", "read_constraints", "propose_week"}
    assert calls[0]["system"]
    # Both reads in turn one are answered before the proposal is accepted.
    assert [b["type"] for b in calls[1]["messages"][-1]["content"]] == ["tool_result", "tool_result"]
    assert [t["tool"] for t in trace].count("claude.reason") == 3
    assert trace[-1] == {"tool": "plan.propose", "status": "completed", "attempt": 1,
                         "latency_ms": 0, "detail": "AI proposal passed deterministic validation."}
    assert {t["status"] for t in trace} == {"completed", "rejected"}
    assert all(set(t) == {"tool", "status", "attempt", "latency_ms", "detail"} for t in trace)


def test_proposal_before_reads_is_rejected_then_repaired(monkeypatch):
    """propose_week is gated on both reads having completed in an earlier turn."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")
    history, guides = demo_history(WEEK), guide_confirmations(WEEK, "baseline")
    valid = generate_plan(history, WEEK, guides=guides).model_dump(mode="json")
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        index = len(calls)
        if index == 1:  # Valid plan, but proposed before reading anything.
            blocks = [use("early", "propose_week", valid)]
        elif index == 2:  # Reads and a proposal in the same turn is still too early.
            blocks = [use("read1", "read_training_history", {}), use("read2", "read_constraints", {}),
                      use("same", "propose_week", valid)]
        else:
            blocks = [use("late", "propose_week", valid)]
        return reply(blocks)

    trace = []
    plan = asyncio.run(propose_with_claude(history, WEEK, "baseline", guides, trace,
                                           transport=httpx.MockTransport(handler)))
    assert plan.athlete_name == "Sara"
    assert len(calls) == 3
    assert calls[1]["messages"][-1]["content"][0]["is_error"] is True
    assert "prior turn" in calls[1]["messages"][-1]["content"][0]["content"]
    assert calls[2]["messages"][-1]["content"][-1]["is_error"] is True
    rejected = [t for t in trace if t["status"] == "rejected"]
    assert [t["tool"] for t in rejected] == ["propose_week", "propose_week"]


def test_model_tool_budget_is_bounded(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")
    calls = []

    def handler(request):
        calls.append(1)
        return reply([use(str(len(calls)), "send_email", {})])

    trace = []
    with pytest.raises(ValueError, match="six-step"):
        asyncio.run(propose_with_claude(demo_history(WEEK), WEEK, "baseline", {}, trace,
                                        httpx.MockTransport(handler)))
    assert len(calls) == 6
    assert all(t["detail"] == "Tool request rejected." for t in trace if t["tool"] == "send_email")


def test_model_returning_no_tool_request_stops_without_actions(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")

    def handler(request):
        return reply([{"type": "text", "text": "I would rather just chat."}])

    with pytest.raises(ValueError, match="without a validated proposal"):
        asyncio.run(propose_with_claude(demo_history(WEEK), WEEK, "baseline", {}, [],
                                        httpx.MockTransport(handler)))


def test_provider_failure_is_reported_without_actions(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")

    def handler(request):
        return httpx.Response(500, json={"error": {"type": "api_error", "message": "boom"}})

    with pytest.raises(ValueError, match="AI provider request failed"):
        asyncio.run(propose_with_claude(demo_history(WEEK), WEEK, "baseline", {}, [],
                                        httpx.MockTransport(handler)))


def test_missing_model_credentials_does_not_fallback_as_ai(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        asyncio.run(propose_with_claude(demo_history(WEEK), WEEK, "baseline", {}, []))


def test_extended_tools_are_declared_but_outside_the_planning_loop(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model")
    for name in ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID",
                 "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"):
        monkeypatch.delenv(name, raising=False)
    assert [t.name for t in EXTENDED_TOOLS] == [
        "tts_say", "session_start", "session_end", "sms_notify", "perception_recent_alerts"]
    assert all(t.description for t in EXTENDED_TOOLS)
    by_name = {t.name: t for t in EXTENDED_TOOLS}
    # Unconfigured optional delivery is an honest marker, never a fabricated clip.
    assert by_name["tts_say"].invoke({"text": "Turn left"}) == "tts_not_configured"
    assert by_name["session_start"].invoke({"plan_item_id": "s1"}).startswith("session_stub")
    assert by_name["session_end"].invoke({"session_id": "s1"}).startswith("session_summary_stub")
    assert by_name["sms_notify"].invoke({"guide_phone": "+10000000000", "text": "hi"}) == "not_configured"
    assert by_name["perception_recent_alerts"].invoke({"session_id": "s1"}) == []
    assert set(by_name["tts_say"].args) == {"text", "priority"}

    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return reply([use("x", "read_training_history", {})])

    with pytest.raises(ValueError, match="six-step"):
        asyncio.run(propose_with_claude(demo_history(WEEK), WEEK, "baseline", {}, [],
                                        httpx.MockTransport(handler)))
    offered = {t["name"] for t in calls[0]["tools"]}
    assert offered.isdisjoint({t.name for t in EXTENDED_TOOLS})


def _tool(name):
    return {t.name: t for t in EXTENDED_TOOLS}[name]


def test_tts_say_tool_speaks_and_caches_a_real_clip(tmp_path, monkeypatch):
    """The tool drives ElevenLabs for real, then serves repeats from the cache."""
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["xi-api-key"] == "secret"
        return httpx.Response(200, content=b"ID3-audio")

    settings = Settings(elevenlabs_api_key="secret", elevenlabs_voice_id="voice", elevenlabs_model_id="model")
    transport = httpx.MockTransport(handler)
    directory = str(tmp_path / "audio")
    monkeypatch.setattr(llm, "speak", lambda text: delivery.speak(text, settings, transport, directory))

    clip = _tool("tts_say").invoke({"text": "Turn left", "priority": "alert"})
    assert re.fullmatch(r"[0-9a-f]{32}", clip)
    assert delivery.read_clip(clip, directory) == b"ID3-audio"
    assert _tool("tts_say").invoke({"text": "Turn left"}) == clip
    assert len(calls) == 1


def test_sms_notify_tool_sends_and_reports_provider_status(monkeypatch):
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(201, json={"sid": "SM5", "status": "queued"})

    settings = Settings(twilio_account_sid="AC1", twilio_auth_token="token", twilio_from_number="+15550000000")
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(llm, "send_sms_notice",
                        lambda to, text: delivery.send_sms_notice(to, text, settings, transport))

    assert _tool("sms_notify").invoke({"guide_phone": "+15551234567", "text": "Moved indoors."}) == "queued:SM5"
    assert len(sent) == 1
