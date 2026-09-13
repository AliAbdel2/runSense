import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import ToolTrace


def record(db: Session, *, tool, step=0, run_id=None, input_json=None, output_json=None, latency_ms=None, retries=0, error=None):
    row = ToolTrace(id=uuid.uuid4().hex, tool=tool, step=step, run_id=run_id, input_json=input_json or {}, output_json=output_json or {}, latency_ms=latency_ms, retries=retries, error=error, created_at=datetime.now(timezone.utc))
    db.add(row); db.commit(); return row


def list_traces(db: Session, run_id=None, limit=200):
    statement = select(ToolTrace).order_by(ToolTrace.step, ToolTrace.created_at, ToolTrace.id).limit(limit)
    if run_id: statement = statement.where(ToolTrace.run_id == run_id)
    return list(db.scalars(statement))
