from __future__ import annotations

from datetime import date

from sqlalchemy import JSON, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PlanWeek(Base):
    __tablename__ = "plan_weeks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    athlete_id: Mapped[str] = mapped_column(String, ForeignKey("athletes.id"), nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    plan_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
