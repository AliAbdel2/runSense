"""Data access for the Streamlit dashboard, with no Streamlit in it.

Every query the page makes lives here as a plain function so it can be unit
tested without a running Streamlit server (``tests/test_dashboard.py``).
``app.py`` is then only layout.

Reads go straight to the typed SQLAlchemy tables via ``runsense.db``, not through
the HTTP API: the dashboard is a local viewer of the same SQLite file the agent
writes, so there is no server to be running and no auth token to hold.
"""

from __future__ import annotations

import asyncio

from runsense.db import db_path
from runsense.observability import recent_alerts as _recent_alerts
from runsense.observability import recent_traces as _recent_traces

DEFAULT_LIMIT = 200


def database_path(path: str | None = None) -> str:
    """The SQLite file being read, so the page can say which one it is showing."""
    return db_path(path)


def recent_traces(run_id: str | None = None, limit: int = DEFAULT_LIMIT,
                  path: str | None = None) -> list[dict]:
    """Recorded tool steps, oldest first, optionally narrowed to one run."""
    return _recent_traces(run_id, limit, path)


def recent_alerts(session_id: str | None = None, tier: str | None = None,
                  limit: int = DEFAULT_LIMIT, path: str | None = None) -> list[dict]:
    """Recorded perception alerts, oldest first, optionally filtered."""
    return _recent_alerts(session_id, tier, limit, path)


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

    ``evaluate()`` is async and Streamlit's script runner is synchronous, so it is
    driven from here rather than from the page. The report keeps the harness's own
    honesty split: measured agent scenarios, and a separately labelled perception
    section that covers triage logic only.
    """
    from runsense.evaluation import evaluate  # noqa: PLC0415 - keeps import cost off the page load

    return asyncio.run(evaluate())


__all__ = ["DEFAULT_LIMIT", "database_path", "evaluation_report", "recent_alerts", "recent_traces",
           "run_ids", "tiers"]
