from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal["baseline", "guide_cancelled", "missed_session", "calendar_retry"] = "baseline"
    week_start: date | None = None
    use_llm: bool = False
    source: Literal["default", "strava"] = "default"
