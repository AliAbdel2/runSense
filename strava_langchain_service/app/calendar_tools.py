"""LangChain tools for creating RunSense sessions in Google Calendar."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .calendar_service import CalendarService


class CalendarToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateCalendarSessionInput(CalendarToolInput):
    title: str = Field(min_length=1, max_length=200)
    start: datetime
    end: datetime
    time_zone: str = Field(default="Europe/Zurich", min_length=1, max_length=100)
    idempotency_key: str = Field(
        min_length=5,
        max_length=200,
        description="Stable key for this athlete and planned session; reuse it for retries.",
    )
    owner_confirmed: bool = Field(
        default=False,
        description="True only when the current user message explicitly asks to create the event.",
    )
    description: str | None = Field(default=None, max_length=4000)
    location: str | None = Field(default=None, max_length=500)
    session_type: Literal["run", "intervals", "long_run", "recovery", "cross_training"] = "run"
    venue_type: Literal["outdoor", "track", "treadmill", "indoor"] = "outdoor"
    guide_email: str | None = Field(default=None, max_length=320)
    reminder_minutes: list[int] = Field(default_factory=lambda: [60, 10], max_length=5)

    @field_validator("start", "end")
    @classmethod
    def offset_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must include a UTC offset")
        return value

    @field_validator("reminder_minutes")
    @classmethod
    def reminders_in_range(cls, values: list[int]) -> list[int]:
        if any(value < 0 or value > 40_320 for value in values):
            raise ValueError("reminder minutes must be between 0 and 40320")
        return values

    @model_validator(mode="after")
    def end_after_start(self):
        if self.end <= self.start:
            raise ValueError("end must be later than start")
        return self


class CalendarEventInput(CalendarToolInput):
    event_id: str = Field(min_length=5, max_length=1024)


class CheckGuideInput(CalendarEventInput):
    guide_email: str = Field(min_length=3, max_length=320)


def build_calendar_tools(service: CalendarService) -> list[BaseTool]:
    @tool("calendar_create_session", args_schema=CreateCalendarSessionInput)
    async def create_session(
        title: str,
        start: datetime,
        end: datetime,
        time_zone: str = "Europe/Zurich",
        idempotency_key: str = "",
        owner_confirmed: bool = False,
        description: str | None = None,
        location: str | None = None,
        session_type: str = "run",
        venue_type: str = "outdoor",
        guide_email: str | None = None,
        reminder_minutes: list[int] | None = None,
    ) -> dict:
        """Create or idempotently update one confirmed training event, optionally inviting a guide."""
        return await service.create_session(
            title=title,
            start=start,
            end=end,
            time_zone=time_zone,
            idempotency_key=idempotency_key,
            owner_confirmed=owner_confirmed,
            description=description,
            location=location,
            session_type=session_type,
            venue_type=venue_type,
            guide_email=guide_email,
            reminder_minutes=reminder_minutes,
        )

    @tool("calendar_get_session", args_schema=CalendarEventInput)
    async def get_session(event_id: str) -> dict:
        """Read back a Calendar session by event ID to verify its saved state."""
        return await service.get_session(event_id)

    @tool("calendar_check_guide", args_schema=CheckGuideInput)
    async def check_guide(event_id: str, guide_email: str) -> dict:
        """Check whether the specifically invited guide accepted, declined, or has not answered."""
        return await service.check_guide(event_id, guide_email)

    return [create_session, get_session, check_guide]
