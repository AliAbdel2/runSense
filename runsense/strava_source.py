"""Personal-use Strava MCP input. Provider data is kept in memory, never on disk.

Tool names and field mappings must come from an authenticated discovery result.
No REST fallback, LLM extraction of distances, or third-party MCP endpoints.
"""
import copy
import asyncio
import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .models import Activity
from .strava_mcp import StravaMCPClient, StravaMCPError


class StravaSourceError(ValueError):
    """A safe message without provider payloads, secrets, or activity contents."""


def _is_safe_read_tool(tool: Any) -> bool:
    """Allow only tools that explicitly advertise read-only behavior."""
    annotations = tool.get("annotations") if isinstance(tool, dict) else None
    if not isinstance(annotations, dict):
        return False
    destructive = annotations.get("destructiveHint")
    return annotations.get("readOnlyHint") is True and (destructive is None or destructive is False)


@dataclass(frozen=True)
class StravaConfig:
    activity_tool: str = ""
    arguments_json: str = "{}"
    rows_pointer: str = "/activities"
    date_field: str = "start_date_local"
    distance_field: str = "distance"
    distance_unit: str = "meters"
    sport_field: str = "sport_type"
    id_field: str = "id"

    @classmethod
    def from_env(cls):
        return cls(
            activity_tool=os.getenv("STRAVA_MCP_ACTIVITY_TOOL", ""),
            arguments_json=os.getenv("STRAVA_MCP_ACTIVITY_ARGUMENTS_JSON", "{}"),
            rows_pointer=os.getenv("STRAVA_MCP_ROWS_POINTER", "/activities"),
            date_field=os.getenv("STRAVA_MCP_DATE_FIELD", "start_date_local"),
            distance_field=os.getenv("STRAVA_MCP_DISTANCE_FIELD", "distance"),
            distance_unit=os.getenv("STRAVA_MCP_DISTANCE_UNIT", "meters"),
            sport_field=os.getenv("STRAVA_MCP_SPORT_FIELD", "sport_type"),
            id_field=os.getenv("STRAVA_MCP_ID_FIELD", "id"),
        )

    def arguments(self, week_start: date) -> dict:
        if len(self.arguments_json) > 16_384:
            raise StravaSourceError("The configured MCP tool arguments are too large.")
        try:
            args = json.loads(self.arguments_json)
        except ValueError as exc:
            raise StravaSourceError("STRAVA_MCP_ACTIVITY_ARGUMENTS_JSON must be a JSON object.") from exc
        if not isinstance(args, dict):
            raise StravaSourceError("STRAVA_MCP_ACTIVITY_ARGUMENTS_JSON must be a JSON object.")
        start = week_start - timedelta(days=21)
        epoch = lambda day: int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        values = {"${week_start}": week_start.isoformat(), "${after_date}": start.isoformat(),
                  "${before_date}": week_start.isoformat(), "${after_epoch}": epoch(start),
                  "${before_epoch}": epoch(week_start)}

        def expand(value):
            if isinstance(value, str):
                if value in values:
                    return values[value]
                if "${" in value:
                    raise StravaSourceError("Unknown or embedded MCP date placeholder; use a documented whole-string placeholder.")
                return value
            if isinstance(value, list):
                return [expand(item) for item in value]
            if isinstance(value, dict):
                return {key: expand(item) for key, item in value.items()}
            return value
        return expand(args)


def pointer(document: Any, path: str):
    """RFC 6901 JSON pointer; no evaluation of remote strings or code."""
    if path == "":
        return document
    if not path.startswith("/"):
        raise StravaSourceError("STRAVA_MCP_ROWS_POINTER must be empty or start with '/'.")
    try:
        for encoded in path[1:].split("/"):
            part = encoded.replace("~1", "/").replace("~0", "~")
            if isinstance(document, list):
                if not part.isdigit() or (len(part) > 1 and part.startswith("0")):
                    raise KeyError
                document = document[int(part)]
            else:
                document = document[part]
        return document
    except (KeyError, IndexError, TypeError) as exc:
        raise StravaSourceError("The MCP result does not match STRAVA_MCP_ROWS_POINTER. Inspect the discovered tool schema and configure the mapping.") from exc


def activity_document(result: dict):
    if result.get("isError"):
        raise StravaSourceError("The Strava activity tool returned an error. Check account eligibility and tool arguments.")
    if result.get("structuredContent") is not None:
        return result["structuredContent"]
    documents = []
    for item in result.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            try:
                documents.append(json.loads(item.get("text", "")))
            except (ValueError, TypeError):
                continue
    if len(documents) != 1:
        raise StravaSourceError("This activity tool did not return one structured JSON document. Choose a structured activity-history tool; prose is not treated as training data.")
    return documents[0]


def normalize_activities(result: dict, config: StravaConfig, week_start: date) -> list[Activity]:
    document = activity_document(result)
    # Fail on explicit truncation instead of treating a partial history as complete.
    if isinstance(document, dict) and any(document.get(key) for key in ("has_more", "hasMore", "next_cursor", "nextCursor", "next_page", "nextPage")):
        raise StravaSourceError("The activity response is paginated. Configure a tool/date range that returns the complete three-week window; partial history is rejected.")
    rows = pointer(document, config.rows_pointer)
    if not isinstance(rows, list) or len(rows) > 1000:
        raise StravaSourceError("The mapped activity result must be an array of at most 1,000 rows.")
    if config.distance_unit not in ("meters", "kilometers"):
        raise StravaSourceError("STRAVA_MCP_DISTANCE_UNIT must be meters or kilometers.")
    activities, seen = [], {}
    for row in rows:
        if not isinstance(row, dict):
            raise StravaSourceError("The activity result contains a non-object row.")
        try:
            activity_id = row[config.id_field]
            day_value = row[config.date_field]
            distance = row[config.distance_field]
            sport = row[config.sport_field]
            if isinstance(activity_id, bool) or not isinstance(activity_id, (str, int)) or str(activity_id) == "":
                raise ValueError
            if not isinstance(day_value, str) or not isinstance(sport, str) or isinstance(distance, bool):
                raise ValueError
            parsed = datetime.fromisoformat(day_value.replace("Z", "+00:00")) if "T" in day_value else date.fromisoformat(day_value)
            day = parsed.date() if isinstance(parsed, datetime) else parsed
            distance = float(distance)
            if not math.isfinite(distance) or distance < 0:
                raise ValueError
            km = distance / 1000 if config.distance_unit == "meters" else distance
            signature = (day, distance, sport)
            identity = str(activity_id)
            if identity in seen:
                if seen[identity] != signature:
                    raise StravaSourceError("The MCP result contains conflicting rows with the same activity ID.")
                continue
            seen[identity] = signature
            # Cycling, walks and other sports must not inflate the running load.
            if sport.lower().replace(" ", "").replace("_", "") not in ("run", "trailrun", "virtualrun", "treadmillrun"):
                continue
            if week_start - timedelta(days=21) <= day < week_start:
                activities.append(Activity(date=day, km=km, kind="easy", completed=True, source="strava_mcp"))
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, StravaSourceError):
                raise
            raise StravaSourceError("An activity does not match the configured date, distance, sport, or ID fields. No plan was generated.") from exc
    if not activities:
        raise StravaSourceError("No running activities were returned in the three-week planning window. Check the date range, mapping and account access.")
    return sorted(activities, key=lambda activity: (activity.date, activity.km))


class StravaSource:
    """Process-local connection state and expiring previews for one personal account."""
    ttl_seconds = 3600

    def __init__(self, client_factory=None, clock=None):
        self.client_factory = client_factory or StravaMCPClient
        self.clock = clock or time.monotonic
        self._disconnected = False
        self._disconnect_fingerprint = None
        self._fingerprint = None
        self._checked_at = 0
        self._tools = []
        self._status = "not_connected"
        self._detail = "Configure an independently authorized Strava MCP access token on the server. A REST API token is not interchangeable."
        self._previews = {}
        self._expiry_handle = None

    def _clear_previews(self):
        self._previews.clear()
        if self._expiry_handle:
            self._expiry_handle.cancel()
            self._expiry_handle = None

    def _token(self) -> str:
        token = os.getenv("STRAVA_MCP_ACCESS_TOKEN", "")
        fingerprint = hashlib.sha256(token.encode()).hexdigest() if token else None
        if fingerprint != self._fingerprint:
            self._clear_previews()
            self._tools = []
            self._checked_at = 0
            self._fingerprint = fingerprint
            # A newly configured token is an explicit local reconnect after a
            # disconnect. Keep a same-token disconnect in effect until the
            # user rotates the token or restarts the process.
            if token and self._disconnected and fingerprint != self._disconnect_fingerprint:
                self._disconnected = False
                self._disconnect_fingerprint = None
            self._status = "configured_unverified" if token else "not_connected"
            self._detail = "MCP token configured. Check access to discover the tools available to your account." if token else "Configure a Strava MCP OAuth access token on the server; a REST API token is not interchangeable."
        return "" if self._disconnected else token

    def status(self) -> dict:
        token = self._token()
        if self.clock() - self._checked_at > self.ttl_seconds:
            self._tools = []
            if self._status == "connected":
                self._status = "configured_unverified"
                self._detail = "Connection verification expired. Check access again."
        config = StravaConfig.from_env()
        configured_tool = next((t for t in self._tools if t.get("name") == config.activity_tool), None)
        return {"status": self._status if token else "not_connected", "detail": self._detail,
                "configured": bool(token), "tool_configured": bool(configured_tool and _is_safe_read_tool(configured_tool)),
                "tools": [{"name": t["name"], "description": t.get("description", ""), "inputSchema": t.get("inputSchema", {})} for t in self._tools],
                "auth_method": "access_token", "personal_use": True, "retention": "memory_only"}

    async def check(self) -> dict:
        token = self._token()
        if not token:
            return self.status()
        try:
            async with self.client_factory(token) as client:
                await client.initialize()
                self._tools = await client.list_tools()
            self._status = "connected"
            self._detail = "Official MCP handshake and tool discovery succeeded. Activity access still depends on subscription eligibility and the selected tool."
            self._checked_at = self.clock()
        except StravaMCPError as exc:
            self._tools = []
            self._clear_previews()
            self._status = "access_denied" if exc.status_code in (401, 403) else "error"
            self._detail = str(exc)
        return self.status()

    async def get_activities(self, week_start: date, trace: list) -> list[Activity]:
        token = self._token()
        if not token:
            raise StravaSourceError("Strava MCP is not connected. Set STRAVA_MCP_ACCESS_TOKEN on the server, then check access.")
        config = StravaConfig.from_env()
        if not config.activity_tool:
            self._clear_previews()
            self._status = "error"
            self._detail = "Choose a tool from authenticated discovery and set STRAVA_MCP_ACTIVITY_TOOL before planning."
            raise StravaSourceError("Choose a tool from authenticated discovery and set STRAVA_MCP_ACTIVITY_TOOL before planning.")
        started = time.perf_counter()
        try:
            async with self.client_factory(token) as client:
                await client.initialize()
                tools = await client.list_tools()
                selected = next((t for t in tools if t.get("name") == config.activity_tool), None)
                if selected is None:
                    raise StravaSourceError("The configured activity tool is not available to this Strava account. Check rollout eligibility and tool discovery.")
                if not _is_safe_read_tool(selected):
                    raise StravaSourceError("The configured tool is not read-only. RunSense only reads activity history.")
                result = await client.call_tool(config.activity_tool, config.arguments(week_start))
            history = normalize_activities(result, config, week_start)
        except StravaMCPError as exc:
            self._clear_previews()
            self._tools = []
            self._status = "access_denied" if exc.status_code in (401, 403) else "error"
            self._detail = str(exc)
            raise
        except StravaSourceError as exc:
            self._clear_previews()
            self._status = "error"
            self._detail = str(exc)
            raise
        self._tools, self._status, self._checked_at = tools, "connected", self.clock()
        trace.append({"tool": "strava_mcp.read_activities", "status": "completed", "attempt": 1,
                      "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                      "detail": "Official MCP activity read and deterministic field mapping completed. Raw results are not logged or saved."})
        return history

    def save_preview(self, result: dict):
        self._prune()
        # Bound even short-lived data; retain only the latest personal preview.
        self._clear_previews()
        self._previews[result["run_id"]] = (self.clock(), copy.deepcopy(result))
        try:
            self._expiry_handle = asyncio.get_running_loop().call_later(self.ttl_seconds, self._clear_previews)
        except RuntimeError:
            # Synchronous callers still get expiry enforcement on every access.
            pass

    def _prune(self):
        self._token()
        now = self.clock()
        self._previews = {key: entry for key, entry in self._previews.items() if now - entry[0] < self.ttl_seconds}

    def get_preview(self, run_id: str) -> dict | None:
        self._prune()
        entry = self._previews.get(run_id)
        return copy.deepcopy(entry[1]) if entry else None

    def disconnect(self) -> dict:
        token = os.getenv("STRAVA_MCP_ACCESS_TOKEN", "")
        self._disconnect_fingerprint = hashlib.sha256(token.encode()).hexdigest() if token else None
        self._disconnected = True
        self._tools = []
        self._clear_previews()
        self._status = "not_connected"
        self._detail = "Disconnected locally and cleared personal previews. Revoke the grant in Strava settings to disconnect at the provider; configure a new token to reconnect."
        return self.status()
