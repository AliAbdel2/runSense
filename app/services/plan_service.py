from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Literal

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session as DbSession

from app.models import Session
from app.repositories.activity_repository import list_in_range
from app.repositories.athlete_repository import get_or_create
from app.repositories.plan_week_repository import upsert as upsert_plan
from app.repositories.session_repository import upsert as upsert_session
from app.services.plan_validation import TRAILING_DAYS, compute_baseline, validate_plan


class PlanValidationError(ValueError):
    """The generated plan failed one or more of the four safety checks.

    Carries the full validation evidence block (not just a summary string) so
    a caller — e.g. the agent's plan tool — can report exactly which rule(s)
    failed instead of only a flattened message.
    """
    def __init__(self, validation: dict):
        self.validation = validation
        failed = [c["name"] for c in validation["checks"] if not c["passed"]]
        super().__init__(f"Generated plan failed validation ({', '.join(failed)}); it was not persisted.")


def next_monday(value=None):
    value = value or date.today(); return value + timedelta(days=(7 - value.weekday()) % 7)


class PlanService:
    """Generate, validate and persist the training week used by the Flutter client."""
    def __init__(self, db: DbSession): self.db = db

    def create(self, *, week_start: date | None = None, scenario="baseline", athlete_id="sara", athlete_name="Sara"):
        week_start = week_start or next_monday()
        if week_start.weekday() != 0: raise ValueError("week_start must be a Monday")
        get_or_create(self.db, athlete_id, athlete_name)

        recent_activities = list_in_range(self.db, athlete_id, week_start - timedelta(days=TRAILING_DAYS), week_start)
        baseline = compute_baseline(recent_activities, week_start)
        target = baseline["km"] * (0.8 if scenario == "missed_session" else 1.0)

        values = [("rest", 0, "home", "not_required"), ("intervals", round(target * .26, 1), "track", "accepted"), ("rest", 0, "home", "not_required"), ("easy", round(target * .21, 1), "treadmill", "not_required"), ("rest", 0, "home", "not_required"), ("long", round(target * .53, 1), "track", "accepted"), ("rest", 0, "home", "not_required")]
        sessions = []
        for offset, (kind, km, venue, guide) in enumerate(values):
            if scenario == "guide_cancelled" and offset == 1: venue, guide = "treadmill", "declined"
            if scenario == "missed_session" and kind == "intervals": kind = "easy"
            day = week_start + timedelta(days=offset); session_id = uuid.uuid5(uuid.NAMESPACE_URL, f"runsense:{athlete_id}:{day.isoformat()}").hex
            spoken = "Rest day. No running scheduled." if kind == "rest" else f"{kind.title()} run for {km:g} kilometres at the {venue}."
            sessions.append({"id": session_id, "athlete_id": athlete_id, "date": day.isoformat(), "kind": kind, "km": km, "venue": venue, "guide_status": guide, "spoken_summary": spoken, "rationale": "A confirmed guide supports this outdoor session." if guide == "accepted" else "No guide is confirmed, so this session stays indoors."})

        baseline_note = "" if baseline["source"] == "derived" else " No recent activity history was found, so this baseline was defaulted, not derived."
        rationale = {"baseline": "A steady week based on the recent training baseline.", "guide_cancelled": "Tuesday's guide cancelled; the same session moves indoors with its identity and distance preserved.", "missed_session": "A missed session calls for a lighter week with intervals replaced by easy running."}.get(scenario, "A steady week based on the recent training baseline.") + baseline_note

        plan = {"id": uuid.uuid4().hex, "week_start": week_start.isoformat(), "athlete_id": athlete_id, "athlete_name": athlete_name, "goal": "A comfortable, consistent 5K", "week_km": round(sum(s["km"] for s in sessions), 1), "baseline_km": baseline["km"], "scenario": scenario, "rationale": rationale, "sessions": sessions}

        validation = validate_plan(plan)
        if not validation["passed"]:
            raise PlanValidationError(validation)

        upsert_plan(self.db, plan, athlete_id)
        for item in sessions:
            upsert_session(self.db, {"id": item["id"], "athlete_id": athlete_id, "plan_week_id": plan["id"], "name": item["spoken_summary"], "sport_type": "Run", "kind": item["kind"], "session_date": date.fromisoformat(item["date"]), "km": item["km"], "state": "planned", "guide_status": item["guide_status"], "summary_json": {"venue": item["venue"], "rationale": item["rationale"]}})

        plan["baseline"] = baseline
        plan["validation"] = validation
        return plan


class CreatePlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal["baseline", "guide_cancelled", "missed_session", "calendar_retry"] = "baseline"
    week_start: date | None = None


def build_plan_tools(service: PlanService) -> list[BaseTool]:
    @tool("plan_create_week", args_schema=CreatePlanInput)
    def create_week(scenario: str = "baseline", week_start: date | None = None) -> dict:
        """Generate this week's training plan from the athlete's real Strava
        history and validate it against the four safety rules (volume cap,
        hard-day spacing, guide requirement, spoken summary length). Always
        returns a result — on a validation failure it reports the violations
        instead of raising, so report success or failure back to the user."""
        try:
            return service.create(scenario=scenario, week_start=week_start)
        except PlanValidationError as exc:
            return {"created": False, "scenario": scenario, "error": str(exc), "validation": exc.validation}
        except ValueError as exc:
            return {"created": False, "scenario": scenario, "error": str(exc)}
    return [create_week]
