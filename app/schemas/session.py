from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartSessionRequest(StrictSchema):
    name: str = Field(default="RunSense Run", min_length=1, max_length=100)
    sport_type: Literal["Run", "TrailRun", "VirtualRun"] = "Run"
    started_at: datetime | None = None


class LocationSample(StrictSchema):
    timestamp: datetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(default=10, gt=0, le=10_000)
    altitude_m: float | None = Field(default=None, ge=-500, le=10_000)
    heart_rate_bpm: int | None = Field(default=None, ge=20, le=250)
    cadence_spm: int | None = Field(default=None, ge=0, le=300)


class SampleBatch(StrictSchema):
    samples: list[LocationSample] = Field(min_length=1, max_length=200)


class SessionTimeRequest(StrictSchema):
    at: datetime | None = None


class StravaUploadRequest(StrictSchema):
    owner_confirmed: bool = False
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    trainer: bool = False
    commute: bool = False
