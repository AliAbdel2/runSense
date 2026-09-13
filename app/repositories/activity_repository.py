from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Activity


def list_recent(db: Session, athlete_id="sara", limit=200):
    return list(db.scalars(select(Activity).where(Activity.athlete_id == athlete_id).order_by(Activity.date.desc()).limit(limit)))


def upsert(db: Session, row: Activity) -> Activity:
    existing = db.get(Activity, row.id)
    if existing is None: db.add(row)
    else:
        for key in ("athlete_id", "strava_id", "date", "km", "avg_pace", "avg_hr", "elevation"): setattr(existing, key, getattr(row, key))
        row = existing
    db.commit(); return row
