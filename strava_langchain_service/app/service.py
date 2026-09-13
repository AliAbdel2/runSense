"""Normalization and matching shared by HTTP routes and LangChain tools."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from .strava_client import StravaClient, StravaInputError


RUN_SPORTS = frozenset({"Run", "TrailRun", "VirtualRun", "TreadmillRun"})
ALLOWED_STREAMS = frozenset(
    {"time", "distance", "velocity_smooth", "heartrate", "moving", "cadence", "altitude"}
)
DEFAULT_STREAMS = ["time", "distance", "velocity_smooth", "heartrate", "moving"]


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def normalize_activity(row: dict[str, Any]) -> dict[str, Any]:
    distance = number(row.get("distance"))
    speed = number(row.get("average_speed"))
    started = parse_time(row.get("start_date")) or parse_time(row.get("start_date_local"))
    pace = 1000 / 60 / speed if speed and speed > 0 else None
    return {
        "id": row.get("id"),
        "name": row.get("name") if isinstance(row.get("name"), str) else None,
        "sport_type": row.get("sport_type") or row.get("type"),
        "date": started.date().isoformat() if started else None,
        "start_date": started.isoformat().replace("+00:00", "Z") if started else None,
        "distance_m": round(distance, 2) if distance is not None else None,
        "distance_km": round(distance / 1000, 3) if distance is not None else None,
        "moving_time_s": row.get("moving_time") if isinstance(row.get("moving_time"), int) else None,
        "elapsed_time_s": row.get("elapsed_time") if isinstance(row.get("elapsed_time"), int) else None,
        "elevation_gain_m": number(row.get("total_elevation_gain")),
        "average_speed_mps": speed,
        "pace_min_per_km": round(pace, 3) if pace is not None else None,
        "has_heartrate": row.get("has_heartrate") is True,
        "average_heartrate_bpm": number(row.get("average_heartrate")),
        "max_heartrate_bpm": number(row.get("max_heartrate")),
        "trainer": row.get("trainer") is True,
        "manual": row.get("manual") is True,
        "workout_type": row.get("workout_type"),
    }


class StravaService:
    def __init__(self, client: StravaClient):
        self.client = client

    async def athlete(self):
        return (await self.client.get_athlete()).as_dict()

    async def raw_activities(self, after=None, before=None, page=1, per_page=100):
        return (
            await self.client.list_activities(
                after=after, before=before, page=page, per_page=per_page
            )
        ).as_dict()

    async def training_history(self, after: int, before: int | None = None, page=1, per_page=100):
        response = await self.client.list_activities(
            after=after, before=before, page=page, per_page=per_page
        )
        activities = [
            normalize_activity(row)
            for row in response.data
            if isinstance(row, dict) and (row.get("sport_type") or row.get("type")) in RUN_SPORTS
        ]
        return {
            "activities": activities,
            "summary": {
                "activity_count": len(activities),
                "total_distance_km": round(sum(a["distance_km"] or 0 for a in activities), 3),
                "activities_with_heartrate": sum(a["has_heartrate"] for a in activities),
            },
            "meta": {"provider_status": response.status_code, "rate_limits": response.rate_limits},
        }

    async def activity(self, activity_id: int, include_all_efforts=False):
        return (await self.client.get_activity(activity_id, include_all_efforts)).as_dict()

    async def laps(self, activity_id: int):
        return (await self.client.get_laps(activity_id)).as_dict()

    async def streams(self, activity_id: int, keys: list[str] | None = None):
        selected = list(dict.fromkeys(keys or DEFAULT_STREAMS))
        unknown = sorted(set(selected) - ALLOWED_STREAMS)
        if unknown:
            raise StravaInputError(f"Unsupported stream keys: {', '.join(unknown)}")
        return (await self.client.get_streams(activity_id, selected)).as_dict()

    async def zones(self):
        return (await self.client.get_zones()).as_dict()

    async def verify_completed_run(
        self,
        session_start: datetime,
        expected_distance_m: float | None = None,
        max_time_delta_hours: float = 6,
    ):
        if session_start.tzinfo is None:
            session_start = session_start.replace(tzinfo=timezone.utc)
        session_start = session_start.astimezone(timezone.utc)
        response = await self.client.list_activities(
            after=max(0, int(session_start.timestamp()) - 900), per_page=30
        )
        candidates = []
        for row in response.data:
            if not isinstance(row, dict) or (row.get("sport_type") or row.get("type")) not in RUN_SPORTS:
                continue
            started = parse_time(row.get("start_date")) or parse_time(row.get("start_date_local"))
            if not started:
                continue
            delta = abs((started - session_start).total_seconds())
            if delta > max_time_delta_hours * 3600:
                continue
            normalized = normalize_activity(row)
            ratio = None
            if expected_distance_m and normalized["distance_m"] is not None:
                ratio = normalized["distance_m"] / expected_distance_m
            score = delta / 3600 + (abs(1 - ratio) if ratio is not None else 0)
            candidates.append((score, delta, ratio, normalized))
        candidates.sort(key=lambda item: (item[0], item[1]))
        best = candidates[0] if candidates else None
        return {
            "matched": best is not None,
            "activity": best[3] if best else None,
            "comparison": {
                "start_delta_seconds": round(best[1], 1) if best else None,
                "distance_completion_ratio": round(best[2], 3) if best and best[2] is not None else None,
            },
            "candidate_count": len(candidates),
            "meta": {"provider_status": response.status_code, "rate_limits": response.rate_limits},
        }
