"""Data access for the Streamlit dashboard, with no Streamlit in it.

Every query the page makes lives here as a plain function so it can be unit
tested without a running Streamlit server (``tests/test_dashboard.py``).
``app.py`` is then only layout.

Reads go straight to the typed SQLAlchemy tables via ``app.models``, not through
the HTTP API: the dashboard is a local viewer of the same SQLite file the agent
writes, so there is no server to be running and no auth token to hold.
"""

from __future__ import annotations

import os
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.models import Alert, ToolTrace


def _engine(path=None):
    path = path or os.getenv("RUNSENSE_DB", "data/runsense.sqlite3")
    return create_engine(os.getenv("RUNSENSE_DATABASE_URL", f"sqlite+pysqlite:///{path}"), future=True)

DEFAULT_LIMIT = 200


def database_path(path: str | None = None) -> str:
    """The SQLite file being read, so the page can say which one it is showing."""
    return path or os.getenv("RUNSENSE_DB", "data/runsense.sqlite3")


def recent_traces(run_id: str | None = None, limit: int = DEFAULT_LIMIT,
                  path: str | None = None) -> list[dict]:
    """Recorded tool steps, oldest first, optionally narrowed to one run."""
    with Session(_engine(path)) as db:
        statement = select(ToolTrace).order_by(ToolTrace.step, ToolTrace.created_at).limit(limit)
        if run_id: statement = statement.where(ToolTrace.run_id == run_id)
        return [{"id": row.id, "run_id": row.run_id, "step": row.step, "tool": row.tool, "input_json": row.input_json, "output_json": row.output_json, "latency_ms": row.latency_ms, "retries": row.retries, "error": row.error, "created_at": row.created_at.isoformat()} for row in db.scalars(statement)]


def recent_alerts(session_id: str | None = None, tier: str | None = None,
                  limit: int = DEFAULT_LIMIT, path: str | None = None) -> list[dict]:
    """Recorded perception alerts, oldest first, optionally filtered."""
    with Session(_engine(path)) as db:
        statement = select(Alert).order_by(Alert.ts, Alert.id).limit(limit)
        if session_id: statement = statement.where(Alert.session_id == session_id)
        if tier: statement = statement.where(Alert.tier == tier)
        return [{"id": row.id, "session_id": row.session_id, "ts": row.ts.isoformat(), "obj_class": row.obj_class, "zone": row.zone, "distance_bucket": row.distance_bucket, "tier": row.tier, "latency_ms": row.latency_ms, "spoken": row.spoken} for row in db.scalars(statement)]


def run_ids(limit: int = DEFAULT_LIMIT, path: str | None = None) -> list[str]:
    """Distinct run ids present in the trace table, most recently recorded first."""
    seen: list[str] = []
    for row in reversed(recent_traces(None, limit, path)):
        if row["run_id"] and row["run_id"] not in seen:
            seen.append(row["run_id"])
    return seen


def tiers(limit: int = DEFAULT_LIMIT, path: str | None = None) -> list[str]:
    """Distinct alert tiers present, for the tier filter."""
    return sorted({row["tier"] for row in recent_alerts(None, None, limit, path)})


def evaluation_report() -> dict:
    """Run the evaluation harness on demand and return its report.

    The new app architecture does not ship the old synthetic evaluation harness;
    keep this endpoint-shaped return value so the dashboard remains renderable.
    """
    return {"passed": 0, "total": 0, "results": [], "scope": "Evaluation service is not configured in the app scaffold.", "perception": {}}


__all__ = ["DEFAULT_LIMIT", "database_path", "evaluation_report", "recent_alerts", "recent_traces",
           "run_ids", "tiers"]
