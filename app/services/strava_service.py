from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DbSession
from app.models import Activity


class StravaError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        self.safe_message, self.status_code = message, status_code
        super().__init__(message + (f" (provider status {status_code})" if status_code else ""))


class StravaInputError(StravaError): pass


@dataclass(frozen=True)
class ProviderResponse:
    data: Any
    status_code: int
    rate_limits: dict

    def as_dict(self): return {"data": self.data, "meta": {"provider_status": self.status_code, "rate_limits": self.rate_limits}}


def _pair(value):
    try: return tuple(int(item) for item in value.split(",", 1))
    except (AttributeError, TypeError, ValueError): return (None, None)


def _limits(headers):
    def bucket(prefix):
        limit, usage = _pair(headers.get(f"X{prefix}RateLimit-Limit")), _pair(headers.get(f"X{prefix}RateLimit-Usage"))
        return {"limit_15_min": limit[0], "limit_daily": limit[1], "used_15_min": usage[0], "used_daily": usage[1]}
    return {"overall": bucket("-"), "read": bucket("-Read")}


class StravaClient:
    max_attempts = 4

    def __init__(self, access_token: str, *, base_url="https://www.strava.com/api/v3", transport=None):
        self._token = access_token.strip()
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), transport=transport, timeout=15,
                                         headers={"Accept": "application/json", "User-Agent": "RunSense-Strava-Agent/1.0"})

    async def __aenter__(self): return self
    async def __aexit__(self, *_): await self.close()
    async def close(self): await self._client.aclose()

    async def _request(self, method, path, *, params=None, data=None, files=None, expected=dict, retry=True):
        if not self._token: raise StravaError("STRAVA_ACCESS_TOKEN is not configured")
        for attempt in range(self.max_attempts):
            try: response = await self._client.request(method, path, params=params, data=data, files=files, headers={"Authorization": f"Bearer {self._token}"})
            except httpx.HTTPError as exc: raise StravaError("Strava request failed") from exc
            if retry and (response.status_code == 429 or response.status_code >= 500) and attempt < self.max_attempts - 1:
                try: delay = float(response.headers.get("Retry-After", 0.1 * 2 ** attempt))
                except ValueError: delay = 0.1 * 2 ** attempt
                await asyncio.sleep(min(max(delay, 0), 2)); continue
            if response.status_code >= 400:
                raise StravaError("Strava authentication failed" if response.status_code in (401, 403) else "Strava request failed", response.status_code)
            try: body = response.json()
            except ValueError as exc: raise StravaError("Strava returned invalid JSON", response.status_code) from exc
            if not isinstance(body, expected): raise StravaError("Strava returned an unexpected response shape", response.status_code)
            return ProviderResponse(body, response.status_code, _limits(response.headers))
        raise StravaError("Strava request failed")

    async def get_athlete(self): return await self._request("GET", "/athlete")
    async def list_activities(self, *, after=None, before=None, page=1, per_page=100):
        if page < 1 or not 1 <= per_page <= 200: raise StravaInputError("page must be positive and per_page must be between 1 and 200")
        if after is not None and before is not None and after >= before: raise StravaInputError("after must be earlier than before")
        params = {"page": page, "per_page": per_page}; params.update({k: v for k, v in (("after", after), ("before", before)) if v is not None})
        return await self._request("GET", "/athlete/activities", params=params, expected=list)
    async def get_activity(self, activity_id, include_all_efforts=False):
        if activity_id < 1: raise StravaInputError("activity_id must be positive")
        return await self._request("GET", f"/activities/{activity_id}", params={"include_all_efforts": str(include_all_efforts).lower()})
    async def get_laps(self, activity_id):
        if activity_id < 1: raise StravaInputError("activity_id must be positive")
        return await self._request("GET", f"/activities/{activity_id}/laps", expected=list)
    async def get_streams(self, activity_id, keys):
        if activity_id < 1: raise StravaInputError("activity_id must be positive")
        return await self._request("GET", f"/activities/{activity_id}/streams", params={"keys": ",".join(keys), "key_by_type": "true"})
    async def get_zones(self): return await self._request("GET", "/athlete/zones")
    async def upload_activity(self, tcx: bytes, **kwargs):
        if not tcx: raise StravaInputError("TCX activity data is empty")
        external_id, name = kwargs.get("external_id"), kwargs.get("name")
        if not external_id or not name: raise StravaInputError("external_id and name are required")
        data = {"data_type": "tcx", "external_id": external_id, "name": name, "trainer": str(kwargs.get("trainer", False)).lower(), "commute": str(kwargs.get("commute", False)).lower()}
        if kwargs.get("description"): data["description"] = kwargs["description"]
        return await self._request("POST", "/uploads", data=data, files={"file": (f"{external_id}.tcx", tcx, "application/vnd.garmin.tcx+xml")}, retry=False)
    async def get_upload(self, upload_id):
        if upload_id < 1: raise StravaInputError("upload_id must be positive")
        return await self._request("GET", f"/uploads/{upload_id}")


RUN_SPORTS = {"Run", "TrailRun", "VirtualRun", "TreadmillRun"}
STREAMS = {"time", "distance", "velocity_smooth", "heartrate", "moving", "cadence", "altitude"}
DEFAULT_STREAMS = ["time", "distance", "velocity_smooth", "heartrate", "moving"]


def _timestamp(value):
    if not isinstance(value, str): return None
    try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError: return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _number(value):
    if isinstance(value, bool): return None
    try: value = float(value)
    except (TypeError, ValueError): return None
    return value if math.isfinite(value) else None


def normalize_activity(row: dict) -> dict:
    distance, speed = _number(row.get("distance")), _number(row.get("average_speed")); started = _timestamp(row.get("start_date")) or _timestamp(row.get("start_date_local"))
    pace = 1000 / 60 / speed if speed and speed > 0 else None
    return {"id": row.get("id"), "name": row.get("name") if isinstance(row.get("name"), str) else None, "sport_type": row.get("sport_type") or row.get("type"), "date": started.date().isoformat() if started else None, "start_date": started.isoformat().replace("+00:00", "Z") if started else None, "distance_m": round(distance, 2) if distance is not None else None, "distance_km": round(distance / 1000, 3) if distance is not None else None, "moving_time_s": row.get("moving_time") if isinstance(row.get("moving_time"), int) else None, "elapsed_time_s": row.get("elapsed_time") if isinstance(row.get("elapsed_time"), int) else None, "elevation_gain_m": _number(row.get("total_elevation_gain")), "average_speed_mps": speed, "pace_min_per_km": round(pace, 3) if pace is not None else None, "has_heartrate": row.get("has_heartrate") is True, "average_heartrate_bpm": _number(row.get("average_heartrate")), "max_heartrate_bpm": _number(row.get("max_heartrate")), "trainer": row.get("trainer") is True, "manual": row.get("manual") is True, "workout_type": row.get("workout_type")}


class StravaService:
    def __init__(self, client, db: DbSession | None = None, athlete_id="sara"):
        self.client, self.db, self.athlete_id = client, db, athlete_id
    async def athlete(self): return (await self.client.get_athlete()).as_dict()
    async def raw_activities(self, **kwargs): return (await self.client.list_activities(**kwargs)).as_dict()
    async def training_history(self, after, before=None, page=1, per_page=100):
        result = await self.client.list_activities(after=after, before=before, page=page, per_page=per_page); rows = [normalize_activity(r) for r in result.data if isinstance(r, dict) and (r.get("sport_type") or r.get("type")) in RUN_SPORTS]
        self._persist_activities(rows)
        return {"activities": rows, "summary": {"activity_count": len(rows), "total_distance_km": round(sum(a["distance_km"] or 0 for a in rows), 3), "activities_with_heartrate": sum(a["has_heartrate"] for a in rows)}, "meta": {"provider_status": result.status_code, "rate_limits": result.rate_limits}}

    def _persist_activities(self, rows):
        if self.db is None: return
        from datetime import date
        from app.repositories.athlete_repository import get_or_create
        get_or_create(self.db, self.athlete_id)
        for item in rows:
            if item.get("id") is None or item.get("date") is None or item.get("distance_km") is None: continue
            row_id = f"strava:{item['id']}"; row = self.db.get(Activity, row_id)
            values = {"id": row_id, "athlete_id": self.athlete_id, "strava_id": str(item["id"]), "date": date.fromisoformat(item["date"]), "km": item["distance_km"], "avg_pace": item["pace_min_per_km"], "avg_hr": round(item["average_heartrate_bpm"]) if item["average_heartrate_bpm"] is not None else None, "elevation": item["elevation_gain_m"]}
            if row is None: self.db.add(Activity(**values))
            else:
                for key, value in values.items(): setattr(row, key, value)
        self.db.commit()
    async def activity(self, activity_id, include_all_efforts=False): return (await self.client.get_activity(activity_id, include_all_efforts)).as_dict()
    async def laps(self, activity_id): return (await self.client.get_laps(activity_id)).as_dict()
    async def streams(self, activity_id, keys=None):
        keys = list(dict.fromkeys(keys or DEFAULT_STREAMS)); unknown = sorted(set(keys) - STREAMS)
        if unknown: raise StravaInputError(f"Unsupported stream keys: {', '.join(unknown)}")
        return (await self.client.get_streams(activity_id, keys)).as_dict()
    async def zones(self): return (await self.client.get_zones()).as_dict()
    async def upload_tcx(self, tcx, **kwargs): return (await self.client.upload_activity(tcx, **kwargs)).as_dict()
    async def upload_status(self, upload_id): return (await self.client.get_upload(upload_id)).as_dict()
    async def verify_completed_run(self, session_start, expected_distance_m=None, max_time_delta_hours=6):
        start = (session_start if session_start.tzinfo else session_start.replace(tzinfo=timezone.utc)).astimezone(timezone.utc); result = await self.client.list_activities(after=max(0, int(start.timestamp()) - 900), per_page=30); candidates = []
        for row in result.data:
            began = _timestamp(row.get("start_date")) or _timestamp(row.get("start_date_local")) if isinstance(row, dict) else None
            if not isinstance(row, dict) or (row.get("sport_type") or row.get("type")) not in RUN_SPORTS or not began: continue
            delta = abs((began - start).total_seconds())
            if delta > max_time_delta_hours * 3600: continue
            normalized = normalize_activity(row); ratio = normalized["distance_m"] / expected_distance_m if expected_distance_m and normalized["distance_m"] is not None else None
            candidates.append((delta / 3600 + (abs(1 - ratio) if ratio is not None else 0), delta, ratio, normalized))
        candidates.sort(key=lambda item: (item[0], item[1])); best = candidates[0] if candidates else None
        return {"matched": bool(best), "activity": best[3] if best else None, "comparison": {"start_delta_seconds": round(best[1], 1) if best else None, "distance_completion_ratio": round(best[2], 3) if best and best[2] is not None else None}, "candidate_count": len(candidates), "meta": {"provider_status": result.status_code, "rate_limits": result.rate_limits}}


class ToolInput(BaseModel): model_config = ConfigDict(extra="forbid")
class HistoryInput(ToolInput): weeks: int = Field(default=4, ge=1, le=52); before_epoch: int | None = Field(default=None, ge=0); page: int = Field(default=1, ge=1); per_page: int = Field(default=100, ge=1, le=200)
class ActivityInput(ToolInput): activity_id: int = Field(gt=0)
class ActivityDetailInput(ActivityInput): include_all_efforts: bool = False
class StreamsInput(ActivityInput): keys: list[str] = Field(default_factory=lambda: list(DEFAULT_STREAMS), max_length=7)
class VerifyRunInput(ToolInput): session_start: datetime; expected_distance_m: float | None = Field(default=None, gt=0, le=200_000); max_time_delta_hours: float = Field(default=6, gt=0, le=24)


def build_strava_tools(service: StravaService) -> list[BaseTool]:
    @tool("strava_get_athlete")
    async def athlete():
        """Return the authenticated athlete's minimal Strava profile."""
        result = await service.athlete(); return {"athlete": {k: result["data"].get(k) for k in ("id", "firstname", "lastname", "measurement_preference")}}
    @tool("strava_get_training_history", args_schema=HistoryInput)
    async def history(weeks=4, before_epoch=None, page=1, per_page=100):
        """Return normalized running history without GPS coordinates."""
        end = before_epoch or int(time.time()); return await service.training_history(max(0, end - weeks * 604800), before_epoch, page, per_page)
    @tool("strava_get_activity", args_schema=ActivityDetailInput)
    async def activity(activity_id, include_all_efforts=False):
        """Return one normalized Strava activity."""
        result = await service.activity(activity_id, include_all_efforts); return {"activity": normalize_activity(result["data"]), "meta": result["meta"]}
    @tool("strava_get_activity_streams", args_schema=StreamsInput)
    async def streams(activity_id, keys=None):
        """Return approved non-GPS activity streams."""
        return await service.streams(activity_id, keys)
    @tool("strava_verify_completed_run", args_schema=VerifyRunInput)
    async def verify(session_start, expected_distance_m=None, max_time_delta_hours=6):
        """Match a recently completed Strava run to a live session."""
        return await service.verify_completed_run(session_start, expected_distance_m, max_time_delta_hours)
    return [athlete, history, activity, streams, verify]
