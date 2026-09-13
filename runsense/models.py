from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Activity(StrictModel):
    date: date
    km: float = Field(ge=0, le=200)
    kind: str = Field(default="easy", max_length=40)
    completed: bool = True
    source: Literal["athlete_authored", "synthetic", "strava_mcp"]


class Session(StrictModel):
    id: str
    athlete_id: str = "sara"
    date: date
    kind: Literal["easy", "intervals", "long", "rest"]
    km: float = Field(ge=0, le=100)
    venue: Literal["treadmill", "track", "park", "home"]
    guide_status: Literal["accepted", "pending", "declined", "not_required"]
    spoken_summary: str = Field(min_length=1, max_length=240)
    rationale: str = Field(min_length=1, max_length=600)


class Plan(StrictModel):
    id: str
    week_start: date
    athlete_name: str = "Sara"
    goal: str = "A comfortable, consistent 5K"
    week_km: float = Field(ge=0)
    baseline_km: float = Field(ge=0)
    scenario: str
    rationale: str = Field(min_length=1, max_length=1200)
    sessions: list[Session] = Field(min_length=7, max_length=7)


class PlanRequest(StrictModel):
    scenario: Literal["baseline", "guide_cancelled", "missed_session", "calendar_retry"] = "baseline"
    week_start: date | None = None
    use_llm: bool = False
    source: Literal["default", "strava_mcp"] = "default"


class CommitRequest(StrictModel):
    run_id: str
    approved: bool = False
