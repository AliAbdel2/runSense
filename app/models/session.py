from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    athlete_id: Mapped[str] = mapped_column(String, ForeignKey("athletes.id"), nullable=False)
    plan_week_id: Mapped[str | None] = mapped_column(String, ForeignKey("plan_weeks.id"), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    sport_type: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str | None] = mapped_column(String, nullable=True)
    session_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    km: Mapped[float | None] = mapped_column(Float, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False, default="planned")
    calendar_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    guide_status: Mapped[str] = mapped_column(String, default="not_required", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
