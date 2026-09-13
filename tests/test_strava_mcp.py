"""Contract tests for the read-only official Strava MCP transport."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from runsense.strava_mcp import (
    MAX_RESPONSE_BYTES,
    MCP_ENDPOINT,
    StravaMCPClient,
    StravaMCPError,
)


def run(awaitable):
    return asyncio.run(awaitable)


def rpc_result(request_id, result):
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": request_id, "result": result})


def test_initialize_negotiates_session_and_initialized_notification():
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        assert request.url == MCP_ENDPOINT
        assert request.headers["authorization"] == "Bearer access-token"
        assert request.headers["accept"] == "application/json, text/event-stream"
        if body["method"] == "initialize":
            assert "mcp-session-id" not in request.headers
            assert "mcp-protocol-version" not in request.headers
            assert body["id"] == 1
            assert body["params"]["protocolVersion"] == "2025-11-25"
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {}},
                },
                headers={"Mcp-Session-Id": "session-1"},
            )
        assert body == {"jsonrpc": "2.0", "method": "notifications/initialized"}
        assert request.headers["mcp-session-id"] == "session-1"
        assert request.headers["mcp-protocol-version"] == "2025-06-18"
        return httpx.Response(202)

    async def operation():
        async with StravaMCPClient("access-token", httpx.MockTransport(handler)) as client:
            return await client.initialize(), client.server_protocol_version

    assert run(operation()) == (
        {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {}},
        "2025-06-18",
    )
    assert len(requests) == 2


def test_list_tools_paginates_and_call_tool_accepts_sse_with_unrelated_messages():
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return rpc_result(body["id"], {"protocolVersion": "2025-03-26", "capabilities": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        if body["method"] == "tools/list":
            if body["params"]:
                return rpc_result(body["id"], {"tools": [{"name": "second", "inputSchema": {"type": "object"}}]})
            return rpc_result(body["id"], {"tools": [{"name": "first", "inputSchema": {"type": "object"}}], "nextCursor": "next"})
        assert body["method"] == "tools/call"
        assert body["params"] == {"name": "first", "arguments": {"date": "2026-09-13"}}
        payload = "\n".join(
            [
                "event: message",
                'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{}}',
                "",
                'data: {"jsonrpc":"2.0","id":999,"result":{"ignored":true}}',
                "",
                f'data: {{"jsonrpc":"2.0","id":{body["id"]},"result":{{"content":[{{"type":"text","text":"ok"}}]}}}}',
                "",
            ]
        )
        return httpx.Response(200, content=payload.encode(), headers={"content-type": "text/event-stream"})

    async def operation():
        async with StravaMCPClient("token", httpx.MockTransport(handler)) as client:
            tools = await client.list_tools()
            result = await client.call_tool("first", {"date": "2026-09-13"})
            return tools, result

    assert run(operation()) == (
        [{"name": "first", "inputSchema": {"type": "object"}}, {"name": "second", "inputSchema": {"type": "object"}}],
        {"content": [{"type": "text", "text": "ok"}]},
    )
    list_requests = [json.loads(request.content) for request in requests if request.method == "POST" and request.content]
    assert [item["method"] for item in list_requests] == [
        "initialize", "notifications/initialized", "tools/list", "tools/list", "tools/call"
    ]
    assert list_requests[3]["params"] == {"cursor": "next"}
    assert [item["id"] for item in list_requests if "id" in item] == [1, 2, 3, 4]


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "authentication_required"), (403, "access_denied"), (500, "request_failed")],
)
def test_http_errors_are_safe_and_do_not_retry(status, code):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, content=b"private provider details and token")

    async def operation():
        async with StravaMCPClient("super-secret", httpx.MockTransport(handler)) as client:
            await client.initialize()

    with pytest.raises(StravaMCPError) as caught:
        run(operation())
    error = caught.value
    assert error.code == code
    assert error.status_code == status
    assert "private" not in str(error)
    assert "super-secret" not in str(error)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json={"jsonrpc": "2.0", "id": 999, "result": {}}),
        httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}}),
    ],
)
def test_malformed_or_unmatched_initialize_responses_are_protocol_errors(response):
    def handler(request):
        return response

    async def operation():
        async with StravaMCPClient("token", httpx.MockTransport(handler)) as client:
            await client.initialize()

    with pytest.raises(StravaMCPError) as caught:
        run(operation())
    assert caught.value.code == "protocol_error"


def test_tool_errors_and_oversized_responses_are_rejected():
    phase = {"value": 0}

    def handler(request):
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return rpc_result(body["id"], {"protocolVersion": "2025-03-26", "capabilities": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        if phase["value"] == 0:
            phase["value"] = 1
            return rpc_result(body["id"], {"isError": True, "content": [{"text": "private"}]})
        return httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1), headers={"content-type": "application/json"})

    async def operation():
        async with StravaMCPClient("token", httpx.MockTransport(handler)) as client:
            with pytest.raises(StravaMCPError) as tool_error:
                await client.call_tool("tool", {})
            assert tool_error.value.code == "tool_error"
            with pytest.raises(StravaMCPError) as size_error:
                await client.call_tool("tool", {})
            assert size_error.value.code == "response_too_large"

    run(operation())


class _StopAfterMatchStream(httpx.AsyncByteStream):
    def __init__(self, first_chunk: bytes):
        self.first_chunk = first_chunk
        self.reads = 0

    async def __aiter__(self):
        self.reads += 1
        yield self.first_chunk
        raise AssertionError("client read past the matching SSE event")


def test_sse_returns_after_matching_event_without_waiting_for_stream_close():
    stream = _StopAfterMatchStream(
        b'data: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-11-25","capabilities":{}}}\n\n'
    )

    def handler(request):
        body = json.loads(request.content)
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    async def operation():
        async with StravaMCPClient("token", httpx.MockTransport(handler)) as client:
            return await client.initialize()

    result = run(operation())
    assert result["protocolVersion"] == "2025-11-25"
    assert stream.reads == 1


@pytest.mark.parametrize(
    "tools",
    [
        [{"name": "missing-schema"}],
        [{"name": "" , "inputSchema": {}}],
        [{"name": "same", "inputSchema": {}}, {"name": "same", "inputSchema": {}}],
    ],
)
def test_list_tools_rejects_invalid_shapes_and_duplicate_names(tools):
    def handler(request):
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return rpc_result(body["id"], {"protocolVersion": "2025-11-25", "capabilities": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(202)
        return rpc_result(body["id"], {"tools": tools})

    async def operation():
        async with StravaMCPClient("token", httpx.MockTransport(handler)) as client:
            await client.list_tools()

    with pytest.raises(StravaMCPError) as caught:
        run(operation())
    assert caught.value.code == "protocol_error"


def test_unknown_negotiated_protocol_version_is_rejected_before_notification():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return rpc_result(requests[-1]["id"], {"protocolVersion": "2099-01-01", "capabilities": {}})

    async def operation():
        async with StravaMCPClient("token", httpx.MockTransport(handler)) as client:
            await client.initialize()

    with pytest.raises(StravaMCPError) as caught:
        run(operation())
    assert caught.value.code == "protocol_error"
    assert len(requests) == 1


def test_invalid_arguments_and_empty_token_are_safe():
    with pytest.raises(StravaMCPError) as empty:
        StravaMCPClient(" ")
    assert empty.value.code == "authentication_required"
    client = StravaMCPClient("token", httpx.MockTransport(lambda request: httpx.Response(500)))
    try:
        with pytest.raises(StravaMCPError) as name_error:
            run(client.call_tool("", {}))
        assert name_error.value.code == "invalid_argument"
        with pytest.raises(StravaMCPError) as args_error:
            run(client.call_tool("tool", []))
        assert args_error.value.code == "invalid_argument"
    finally:
        run(client.aclose())
