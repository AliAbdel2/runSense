from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HistoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weeks: int = Field(default=4, ge=1, le=52)
    before: int | None = Field(default=None, ge=0)
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=100, ge=1, le=200)


class CompletedRunQuery(BaseModel):
    session_start: datetime
    expected_distance_m: float | None = Field(default=None, gt=0, le=200_000)
    max_time_delta_hours: float = Field(default=6, gt=0, le=24)
