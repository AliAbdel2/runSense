import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Alert


def record(db: Session, *, session_id=None, obj_class, zone, distance_bucket, tier, latency_ms=None, spoken=False, ts=None):
    row = Alert(id=uuid.uuid4().hex, session_id=session_id, ts=ts or datetime.now(timezone.utc), obj_class=obj_class,
                zone=zone, distance_bucket=distance_bucket, tier=tier, latency_ms=latency_ms, spoken=spoken)
    db.add(row); db.commit(); return row


def list_alerts(db: Session, session_id=None, limit=200):
    statement = select(Alert).order_by(Alert.ts, Alert.id).limit(limit)
    if session_id: statement = statement.where(Alert.session_id == session_id)
    return list(db.scalars(statement))
