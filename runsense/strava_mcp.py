"""Small read-only Streamable HTTP client for the official Strava MCP server.

Authentication is intentionally kept outside this module.  The caller passes
an OAuth access token, and this client only sends MCP initialization, tool
discovery, and tool-call requests to Strava's fixed endpoint.
"""

from __future__ import annotations

import json
import codecs
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Any

import httpx


MCP_ENDPOINT = "https://mcp.strava.com/mcp"
MCP_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = frozenset({"2025-03-26", "2025-06-18", "2025-11-25"})
MAX_TOOL_PAGES = 10
MAX_TOOLS = 100
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class StravaMCPError(RuntimeError):
    """A safe, machine-readable failure from the Strava MCP boundary.

    Exception text is deliberately composed only from constants in this
    module.  Provider response bodies, request arguments, URLs, and tokens
    are never included.
    """

    def __init__(
        self,
        safe_message: str,
        *,
        status_code: int | None = None,
        code: str = "protocol_error",
    ) -> None:
        self.safe_message = safe_message
        self.status_code = status_code
        self.code = code
        suffix = f" (status {status_code})" if status_code is not None else ""
        super().__init__(f"strava mcp: {safe_message}{suffix}")


class StravaMCPClient:
    """An async, read-only MCP client using Streamable HTTP."""

    endpoint = MCP_ENDPOINT
    protocol_version = MCP_PROTOCOL_VERSION
    timeout = 15.0

    def __init__(
        self,
        access_token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not isinstance(access_token, str) or not access_token.strip():
            raise StravaMCPError(
                "an access token is required",
                code="authentication_required",
            )
        self._access_token = access_token
        self._transport = transport
        self._client = httpx.AsyncClient(transport=transport, timeout=self.timeout)
        self._session_id: str | None = None
        self._request_id = 0
        self._initialized = False
        self._closed = False
        self._negotiated_protocol_version: str | None = None

    async def __aenter__(self) -> "StravaMCPClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if not self._closed:
            await self._client.aclose()
            self._closed = True

    async def close(self) -> None:
        """Close the underlying HTTP client (async alias for ``aclose``)."""

        await self.aclose()

    async def initialize(self) -> dict[str, Any]:
        """Negotiate an MCP session and send the required initialized notice."""

        if self._initialized:
            # Initialization is idempotent for callers and avoids creating a
            # second server session by accident.
            return self._initialize_result
        result = await self._initialize_impl()
        self._initialize_result = result
        self._initialized = True
        return result

    async def _initialize_impl(self) -> dict[str, Any]:
        request_id = self._new_request_id()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": self.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "runsense", "version": "0.1.0"},
            },
        }
        response = await self._post_rpc(request, request_id, include_session=False)
        result = self._response_result(response)
        if not isinstance(result, dict):
            raise StravaMCPError("initialize result is invalid", code="protocol_error")
        server_version = result.get("protocolVersion")
        if server_version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise StravaMCPError("server protocol version is missing", code="protocol_error")
        self.server_protocol_version = server_version
        self._negotiated_protocol_version = server_version

        # Notifications have no request id and Streamable HTTP servers normally
        # answer them with 202 and an empty body.  Be liberal about a 200 empty
        # response as some compatible servers use it.
        initialized = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        await self._post_notification(initialized)
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return at most 100 tools across at most ten MCP pages."""

        await self.initialize()
        tools: list[dict[str, Any]] = []
        tool_names: set[str] = set()
        cursor: str | None = None
        for page_number in range(MAX_TOOL_PAGES):
            params: dict[str, Any] = {}
            if cursor is not None:
                params["cursor"] = cursor
            request_id = self._new_request_id()
            request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/list",
                "params": params,
            }
            response = await self._post_rpc(request, request_id)
            result = self._response_result(response)
            if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
                raise StravaMCPError("tool list result is invalid", code="protocol_error")
            for tool in result["tools"]:
                if not isinstance(tool, dict):
                    raise StravaMCPError("tool list result is invalid", code="protocol_error")
                tool_name = tool.get("name")
                input_schema = tool.get("inputSchema")
                if not isinstance(tool_name, str) or not tool_name.strip() or not isinstance(input_schema, dict):
                    raise StravaMCPError("tool list result is invalid", code="protocol_error")
                if tool_name in tool_names:
                    raise StravaMCPError("tool list contains duplicate names", code="protocol_error")
                tool_names.add(tool_name)
                tools.append(tool)
                if len(tools) > MAX_TOOLS:
                    raise StravaMCPError("tool list is too large", code="response_too_large")
            next_cursor = result.get("nextCursor")
            if next_cursor is None or next_cursor == "":
                return tools
            if not isinstance(next_cursor, str):
                raise StravaMCPError("tool list cursor is invalid", code="protocol_error")
            cursor = next_cursor
        raise StravaMCPError("tool list has too many pages", code="response_too_large")

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call one MCP tool and return its raw ``CallToolResult``."""

        if not isinstance(name, str) or not name:
            raise StravaMCPError("tool name is invalid", code="invalid_argument")
        if not isinstance(arguments, dict):
            raise StravaMCPError("tool arguments are invalid", code="invalid_argument")
        await self.initialize()
        request_id = self._new_request_id()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        response = await self._post_rpc(request, request_id)
        result = self._response_result(response)
        if not isinstance(result, dict):
            raise StravaMCPError("tool result is invalid", code="protocol_error")
        if result.get("isError") is True:
            raise StravaMCPError("Strava tool returned an error", code="tool_error")
        return result

    def _new_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _headers(self, *, include_session: bool = True) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._negotiated_protocol_version is not None:
            headers["MCP-Protocol-Version"] = self._negotiated_protocol_version
        if include_session and self._session_id is not None:
            headers["MCP-Session-Id"] = self._session_id
        return headers

    async def _post_notification(self, message: dict[str, Any]) -> None:
        async with self._open_post(message, include_session=True) as response:
            if response.status_code >= 400:
                raise self._http_error(response.status_code)
            if response.status_code in (200, 202):
                body = await self._read_limited(response)
                if not body:
                    return
            raise StravaMCPError("initialized notification response is invalid", code="protocol_error")

    async def _post_rpc(
        self,
        message: dict[str, Any],
        request_id: int,
        *,
        include_session: bool = True,
    ) -> dict[str, Any]:
        async with self._open_post(message, include_session=include_session) as response:
            if response.status_code >= 400:
                raise self._http_error(response.status_code)
            self._record_session(response)
            if response.status_code == 202:
                raise StravaMCPError("server returned no RPC result", code="protocol_error", status_code=202)
            content_type = response.headers.get("content-type", "").lower()
            if "text/event-stream" in content_type:
                candidate = await self._read_sse_response(response, request_id)
                if candidate is None:
                    raise StravaMCPError("RPC response id did not match request", code="protocol_error")
                return self._validated_response(candidate)
            body = await self._read_limited(response)
            messages = self._decode_messages(body)
            for candidate in messages:
                if self._is_matching_response(candidate, request_id):
                    return self._validated_response(candidate)
            raise StravaMCPError("RPC response id did not match request", code="protocol_error")

    @asynccontextmanager
    async def _open_post(self, message: dict[str, Any], *, include_session: bool):
        try:
            async with self._client.stream(
                "POST",
                self.endpoint,
                headers=self._headers(include_session=include_session),
                json=message,
            ) as response:
                yield response
        except StravaMCPError:
            raise
        except (httpx.HTTPError, RuntimeError, TypeError, ValueError, UnicodeError) as exc:
            raise StravaMCPError("request failed", code="request_failed") from exc

    async def _read_limited(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        try:
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise StravaMCPError(
                        "response is too large",
                        code="response_too_large",
                        status_code=response.status_code,
                    )
                chunks.append(chunk)
        except StravaMCPError:
            raise
        except (httpx.HTTPError, RuntimeError, UnicodeError) as exc:
            raise StravaMCPError("response could not be read", code="request_failed") from exc
        return b"".join(chunks)

    async def _read_sse_response(self, response: httpx.Response, request_id: int) -> dict[str, Any] | None:
        decoder = codecs.getincrementaldecoder("utf-8")()
        buffer = ""
        data_lines: list[str] = []
        total = 0

        def finish_event() -> dict[str, Any] | None:
            if not data_lines:
                return None
            raw = "\n".join(data_lines)
            data_lines.clear()
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise StravaMCPError("server returned invalid SSE data", code="protocol_error") from exc
            candidates = value if isinstance(value, list) else [value]
            if not all(isinstance(item, dict) for item in candidates):
                raise StravaMCPError("server returned invalid SSE data", code="protocol_error")
            return next((item for item in candidates if self._is_matching_response(item, request_id)), None)

        def process_line(line: str) -> dict[str, Any] | None:
            line = line.rstrip("\r")
            if line == "":
                return finish_event()
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip(" "))
            return None

        try:
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise StravaMCPError(
                        "response is too large",
                        code="response_too_large",
                        status_code=response.status_code,
                    )
                buffer += decoder.decode(chunk)
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    candidate = process_line(line)
                    if candidate is not None:
                        return candidate
            buffer += decoder.decode(b"", final=True)
        except StravaMCPError:
            raise
        except (httpx.HTTPError, RuntimeError, UnicodeError) as exc:
            raise StravaMCPError("response could not be read", code="request_failed") from exc
        candidate = process_line(buffer) if buffer else None
        return candidate if candidate is not None else finish_event()

    def _record_session(self, response: httpx.Response) -> None:
        session_id = response.headers.get("Mcp-Session-Id")
        if session_id is not None:
            if not session_id or any(ord(char) < 0x21 or ord(char) > 0x7E for char in session_id):
                raise StravaMCPError("server session id is invalid", code="protocol_error")
            self._session_id = session_id

    def _decode_messages(self, body: bytes) -> list[dict[str, Any]]:
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StravaMCPError("server returned invalid JSON", code="protocol_error") from exc
        values = decoded if isinstance(decoded, list) else [decoded]
        if not all(isinstance(value, dict) for value in values):
            raise StravaMCPError("server returned an invalid RPC message", code="protocol_error")
        return values

    @staticmethod
    def _validated_response(candidate: dict[str, Any]) -> dict[str, Any]:
        if "error" in candidate:
            raise StravaMCPError("server returned an RPC error", code="remote_error")
        if "result" not in candidate:
            raise StravaMCPError("RPC response is invalid", code="protocol_error")
        return candidate

    def _decode_sse(self, body: bytes) -> list[dict[str, Any]]:
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StravaMCPError("server returned invalid SSE", code="protocol_error") from exc
        messages: list[dict[str, Any]] = []
        data_lines: list[str] = []

        def finish_event() -> None:
            if not data_lines:
                return
            raw = "\n".join(data_lines)
            data_lines.clear()
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise StravaMCPError("server returned invalid SSE data", code="protocol_error") from exc
            if isinstance(value, list):
                if not all(isinstance(item, dict) for item in value):
                    raise StravaMCPError("server returned invalid SSE data", code="protocol_error")
                messages.extend(value)
            elif isinstance(value, dict):
                messages.append(value)
            else:
                raise StravaMCPError("server returned invalid SSE data", code="protocol_error")

        for line in text.splitlines():
            if line == "":
                finish_event()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip(" "))
            # event/id/retry and comments are metadata; MCP payloads are in
            # data fields only.
        finish_event()
        return messages

    @staticmethod
    def _is_matching_response(message: Mapping[str, Any], request_id: int) -> bool:
        value = message.get("id")
        return message.get("jsonrpc") == "2.0" and type(value) is type(request_id) and value == request_id and (
            "result" in message or "error" in message
        )

    @staticmethod
    def _response_result(response: Mapping[str, Any]) -> Any:
        return response.get("result")

    @staticmethod
    def _http_error(status_code: int) -> StravaMCPError:
        if status_code == 401:
            return StravaMCPError("Strava authentication is required or expired", status_code=status_code, code="authentication_required")
        if status_code == 403:
            return StravaMCPError("Strava access is forbidden for this account", status_code=status_code, code="access_denied")
        if status_code == 404:
            return StravaMCPError("Strava MCP endpoint was not found", status_code=status_code, code="not_found")
        return StravaMCPError("Strava MCP request failed", status_code=status_code, code="request_failed")


__all__ = ["MCP_ENDPOINT", "MCP_PROTOCOL_VERSION", "StravaMCPClient", "StravaMCPError"]
