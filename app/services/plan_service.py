from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy.orm import Session as DbSession

from app.models import Session
from app.repositories.athlete_repository import get_or_create
from app.repositories.plan_week_repository import upsert as upsert_plan
from app.repositories.session_repository import upsert as upsert_session


def next_monday(value=None):
    value = value or date.today(); return value + timedelta(days=(7 - value.weekday()) % 7)


class PlanService:
    """Generate and persist the validated week used by the Flutter client."""
    def __init__(self, db: DbSession): self.db = db
    def history(self):
        return [{"date": (date.today() - timedelta(weeks=weeks)).isoformat(), "km": 19 / 3, "kind": "easy", "completed": True, "source": "synthetic"} for weeks in (1, 2, 3)]
    def create(self, *, week_start: date | None = None, scenario="baseline", athlete_id="sara", athlete_name="Sara"):
        week_start = week_start or next_monday()
        if week_start.weekday() != 0: raise ValueError("week_start must be a Monday")
        get_or_create(self.db, athlete_id, athlete_name); target = 19.0 * (0.8 if scenario == "missed_session" else 1.0)
        values = [("rest", 0, "home", "not_required"), ("intervals", round(target * .26, 1), "track", "accepted"), ("rest", 0, "home", "not_required"), ("easy", round(target * .21, 1), "treadmill", "not_required"), ("rest", 0, "home", "not_required"), ("long", round(target * .53, 1), "track", "accepted"), ("rest", 0, "home", "not_required")]
        sessions = []
        for offset, (kind, km, venue, guide) in enumerate(values):
            if scenario == "guide_cancelled" and offset == 1: venue, guide = "treadmill", "declined"
            if scenario == "missed_session" and kind == "intervals": kind = "easy"
            day = week_start + timedelta(days=offset); session_id = uuid.uuid5(uuid.NAMESPACE_URL, f"runsense:{athlete_id}:{day.isoformat()}").hex
            spoken = "Rest day. No running scheduled." if kind == "rest" else f"{kind.title()} run for {km:g} kilometres at the {venue}."
            sessions.append({"id": session_id, "athlete_id": athlete_id, "date": day.isoformat(), "kind": kind, "km": km, "venue": venue, "guide_status": guide, "spoken_summary": spoken, "rationale": "A confirmed guide supports this outdoor session." if guide == "accepted" else "No guide is confirmed, so this session stays indoors."})
        rationale = {"baseline": "A steady week based on the recent training baseline.", "guide_cancelled": "Tuesday's guide cancelled; the same session moves indoors with its identity and distance preserved.", "missed_session": "A missed session calls for a lighter week with intervals replaced by easy running."}.get(scenario, "A steady week based on the recent training baseline.")
        plan = {"id": uuid.uuid4().hex, "week_start": week_start.isoformat(), "athlete_id": athlete_id, "athlete_name": athlete_name, "goal": "A comfortable, consistent 5K", "week_km": round(sum(s["km"] for s in sessions), 1), "baseline_km": 19.0, "scenario": scenario, "rationale": rationale, "sessions": sessions}
        upsert_plan(self.db, plan, athlete_id)
        for item in sessions:
            upsert_session(self.db, {"id": item["id"], "athlete_id": athlete_id, "plan_week_id": plan["id"], "name": item["spoken_summary"], "sport_type": "Run", "kind": item["kind"], "session_date": date.fromisoformat(item["date"]), "km": item["km"], "state": "planned", "guide_status": item["guide_status"], "summary_json": {"venue": item["venue"], "rationale": item["rationale"]}})
        return plan
