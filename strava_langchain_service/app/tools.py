"""LangChain tools backed by the same service used by the HTTP API."""

from __future__ import annotations

import time
from datetime import datetime

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field

from .service import DEFAULT_STREAMS, StravaService, normalize_activity


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HistoryInput(ToolInput):
    weeks: int = Field(default=4, ge=1, le=52)
    before_epoch: int | None = Field(default=None, ge=0)
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=100, ge=1, le=200)


class ActivityInput(ToolInput):
    activity_id: int = Field(gt=0)


class ActivityDetailInput(ActivityInput):
    include_all_efforts: bool = False


class StreamsInput(ActivityInput):
    keys: list[str] = Field(default_factory=lambda: list(DEFAULT_STREAMS), max_length=7)


class VerifyRunInput(ToolInput):
    session_start: datetime
    expected_distance_m: float | None = Field(default=None, gt=0, le=200_000)
    max_time_delta_hours: float = Field(default=6, gt=0, le=24)


def build_strava_tools(service: StravaService) -> list[BaseTool]:
    @tool("strava_get_athlete")
    async def get_athlete() -> dict:
        """Confirm the authenticated Strava athlete and return a minimal profile."""
        result = await service.athlete()
        row = result["data"]
        return {
            "athlete": {
                "id": row.get("id"),
                "firstname": row.get("firstname"),
                "lastname": row.get("lastname"),
                "measurement_preference": row.get("measurement_preference"),
            },
            "meta": result["meta"],
        }

    @tool("strava_get_training_history", args_schema=HistoryInput)
    async def get_training_history(
        weeks: int = 4,
        before_epoch: int | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> dict:
        """Get normalized running history for load, pace, elevation, and heart-rate analysis."""
        end = before_epoch or int(time.time())
        after = max(0, end - weeks * 7 * 24 * 60 * 60)
        return await service.training_history(after, before_epoch, page, per_page)

    @tool("strava_get_activity", args_schema=ActivityDetailInput)
    async def get_activity(activity_id: int, include_all_efforts: bool = False) -> dict:
        """Get one completed activity by ID and normalize it for plan-versus-actual analysis."""
        result = await service.activity(activity_id, include_all_efforts)
        return {"activity": normalize_activity(result["data"]), "meta": result["meta"]}

    @tool("strava_get_activity_laps", args_schema=ActivityInput)
    async def get_activity_laps(activity_id: int) -> dict:
        """Get recorded laps for interval-workout adherence analysis."""
        result = await service.laps(activity_id)
        keep = {
            "id", "name", "lap_index", "split", "distance", "elapsed_time", "moving_time",
            "average_speed", "max_speed", "average_cadence", "pace_zone", "total_elevation_gain",
        }
        return {
            "laps": [{key: value for key, value in row.items() if key in keep} for row in result["data"]],
            "meta": result["meta"],
        }

    @tool("strava_get_activity_streams", args_schema=StreamsInput)
    async def get_activity_streams(activity_id: int, keys: list[str] | None = None) -> dict:
        """Get time-series pace, distance, heart rate, movement, cadence, or altitude; GPS is excluded."""
        return await service.streams(activity_id, keys)

    @tool("strava_get_hr_zones")
    async def get_hr_zones() -> dict:
        """Get the authenticated athlete's configured heart-rate and power zones."""
        return await service.zones()

    @tool("strava_verify_completed_run", args_schema=VerifyRunInput)
    async def verify_completed_run(
        session_start: datetime,
        expected_distance_m: float | None = None,
        max_time_delta_hours: float = 6,
    ) -> dict:
        """Find the run uploaded near a planned session and compare its completed distance."""
        return await service.verify_completed_run(
            session_start, expected_distance_m, max_time_delta_hours
        )

    return [
        get_athlete,
        get_training_history,
        get_activity,
        get_activity_laps,
        get_activity_streams,
        get_hr_zones,
        verify_completed_run,
    ]
