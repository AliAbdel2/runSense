from datetime import date
from sqlalchemy.orm import Session
from app.models import PlanWeek


def upsert(db: Session, plan: dict, athlete_id="sara") -> PlanWeek:
    row = db.get(PlanWeek, plan["id"])
    if row is None:
        week_start = plan["week_start"]
        if isinstance(week_start, str): week_start = date.fromisoformat(week_start)
        row = PlanWeek(id=plan["id"], athlete_id=athlete_id, week_start=week_start)
        db.add(row)
    row.plan_json, row.rationale = plan, plan.get("rationale", "")
    db.commit(); return row
