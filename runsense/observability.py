"""Best-effort mirror of in-memory traces and perception alerts into the typed tables.

The in-memory ``{"tool","status","attempt","latency_ms","detail"}`` trace dicts and
the blob ``runs`` row stay exactly as they are: the API, the web dashboard and the
evaluation harness all read them and nothing here changes that contract.  This
module adds a *second*, queryable write path into Phase 1's ``tool_traces`` and
``alerts`` tables so a judge can ask cross-run questions the per-run dashboard
cannot answer.

Everything here is optional infrastructure, so it follows the same rule Phase 3's
SMS and TTS calls follow: a failure to record is reported, never raised.  A locked
database, a read-only volume or a missing table must not void an otherwise valid
plan, commit or alert stream.  Every writer returns a count/flag instead of
throwing, and callers are free to ignore it.

Field mapping, trace dict -> ``ToolTrace`` column (the names deliberately differ):

===================  ==========================================================
``tool``             ``tool``
list index           ``step`` (position in the run's own trace list)
``latency_ms``       ``latency_ms``
``attempt``          ``retries`` as ``attempt - 1``; attempt 1 means no retry.
                     The raw attempt number is also kept in ``input_json`` so
                     the lossy subtraction stays reversible.
``status``           ``output_json["status"]``
``detail``           ``output_json["detail"]``, and ``error`` as well when the
                     status is a failing one (``failed``/``rejected``)
===================  ==========================================================
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from typing import Any

from .db import Alert, ToolTrace, TypedStore, db_path, list_alerts, list_tool_traces, record_tool_trace

logger = logging.getLogger(__name__)

#: Trace statuses that mean the step did not do what it set out to do.  These are
#: the only ones that also populate ``ToolTrace.error``; ``retrying`` is a step
#: that recovered, and ``skipped`` is an unconfigured optional integration.
FAILED_STATUSES = frozenset({"failed", "rejected"})

DEFAULT_LIMIT = 200


@lru_cache(maxsize=8)
def _store_for(resolved_path: str) -> TypedStore:
    return TypedStore(resolved_path)


def _typed_store(path: str | None = None) -> TypedStore:
    """One engine per database file.

    ``TypedStore`` builds an engine and runs ``create_all`` on construction, and a
    live alert stream records one row per hazard, so rebuilding it per call would
    put schema round-trips on the alert path. The cache is keyed on the *resolved*
    path, so a later change to ``RUNSENSE_DB`` is still honoured. Failures are not
    cached.
    """
    return _store_for(db_path(path))


def _attempt(entry: dict) -> int:
    try:
        return max(int(entry.get("attempt") or 1), 1)
    except (TypeError, ValueError):
        return 1


def _latency(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def record_trace(trace: list[dict], run_id: str | None = None, *, start: int = 0,
                 path: str | None = None) -> int:
    """Mirror ``trace[start:]`` into ``tool_traces``. Returns rows written.

    ``start`` lets a caller persist only the tail of a trace list that grew after
    an earlier call (``commit`` appends to a run whose planning steps are already
    recorded), keeping ``step`` aligned with the in-memory list index.

    Never raises: a typed-store failure returns the number of rows that did make
    it (possibly 0) and logs, so the caller's run completes exactly as before.
    """
    entries = list(trace[start:])
    if not entries:
        return 0
    written = 0
    try:
        store = _typed_store(path)
        with store.session() as session:
            for offset, entry in enumerate(entries):
                status = entry.get("status")
                detail = entry.get("detail")
                input_json = {"attempt": _attempt(entry)}
                if isinstance(entry.get("input_json"), dict):
                    input_json.update(entry["input_json"])
                elif isinstance(entry.get("input"), dict):
                    input_json.update(entry["input"])
                record_tool_trace(
                    session,
                    tool=str(entry.get("tool") or "unknown"),
                    step=start + offset,
                    run_id=run_id,
                    input_json=input_json,
                    output_json={"status": status, "detail": detail},
                    latency_ms=_latency(entry.get("latency_ms")),
                    retries=_attempt(entry) - 1,
                    error=str(detail) if status in FAILED_STATUSES else None,
                )
                written += 1
    except Exception as exc:  # noqa: BLE001 - optional infrastructure, never fatal
        logger.warning("Tool trace not persisted for run %s: %s", run_id, exc)
    return written


def record_run_trace(result: dict, path: str | None = None) -> int:
    """Record whichever steps of ``result["trace"]`` are not in the table yet.

    The resume offset is read back from the table rather than kept in process
    memory, so committing a run in a restarted process - or retrying a commit that
    appended further steps - appends the new steps instead of duplicating the
    earlier ones. A run without an id is not recorded, because ``run_id=None``
    would make the row unattributable. Never raises.
    """
    run_id = result.get("run_id")
    trace = result.get("trace") or []
    if not run_id or not trace:
        return 0
    try:
        store = _typed_store(path)
        with store.session() as session:
            start = len(list_tool_traces(session, run_id))
    except Exception as exc:  # noqa: BLE001 - optional infrastructure, never fatal
        logger.warning("Tool traces not persisted for run %s: %s", run_id, exc)
        return 0
    return record_trace(trace, run_id, start=start, path=path)


def record_alert_event(event: dict, session_id: str | None = None, *, path: str | None = None) -> bool:
    """Mirror one perception alert dict into ``alerts``. Returns whether it landed.

    Accepts the payload ``perception.run_pipeline`` yields (``AlertEvent.to_dict``
    plus the loop's own timing).  ``distance`` is the triage event's bucket name,
    which is what the ``distance_bucket`` column holds.  Never raises.
    """
    try:
        store = _typed_store(path)
        store.record_alert(
            obj_class=str(event.get("obj_class") or "unknown"),
            zone=str(event.get("zone") or "unknown"),
            distance_bucket=str(event.get("distance") or "unknown"),
            tier=str(event.get("tier") or "unknown"),
            session_id=session_id,
            latency_ms=_latency(event.get("stage_latency_ms")),
            spoken=bool(event.get("spoken")),
        )
        return True
    except Exception as exc:  # noqa: BLE001 - optional infrastructure, never fatal
        logger.warning("Perception alert not persisted for session %s: %s", session_id, exc)
        return False


# --- read side ----------------------------------------------------------
# Shared by the API routes and the Streamlit dashboard so both render the same
# JSON-safe shape from one place.


def _isoformat(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def trace_to_dict(row: ToolTrace) -> dict:
    return {"id": row.id, "run_id": row.run_id, "step": row.step, "tool": row.tool,
            "input_json": row.input_json, "output_json": row.output_json,
            "latency_ms": row.latency_ms, "retries": row.retries, "error": row.error,
            "created_at": _isoformat(row.created_at)}


def alert_to_dict(row: Alert) -> dict:
    return {"id": row.id, "session_id": row.session_id, "ts": _isoformat(row.ts),
            "obj_class": row.obj_class, "zone": row.zone, "distance_bucket": row.distance_bucket,
            "tier": row.tier, "latency_ms": row.latency_ms, "spoken": row.spoken}


def recent_traces(run_id: str | None = None, limit: int = DEFAULT_LIMIT,
                  path: str | None = None) -> list[dict]:
    """The most recent ``limit`` tool traces, oldest first, optionally one run's."""
    store = _typed_store(path)
    with store.session() as session:
        rows = list_tool_traces(session, run_id)
    return [trace_to_dict(row) for row in rows[-max(limit, 0):]] if limit else []


def recent_alerts(session_id: str | None = None, tier: str | None = None,
                  limit: int = DEFAULT_LIMIT, path: str | None = None) -> list[dict]:
    """The most recent ``limit`` alerts, oldest first, optionally filtered.

    ``session_id`` is pushed down to the query; ``tier`` has no index or helper in
    Phase 1's schema, so it is filtered here rather than by widening ``db.py``.
    """
    store = _typed_store(path)
    with store.session() as session:
        rows = list_alerts(session, session_id)
    if tier is not None:
        rows = [row for row in rows if row.tier == tier]
    return [alert_to_dict(row) for row in rows[-max(limit, 0):]] if limit else []


__all__ = [
    "DEFAULT_LIMIT",
    "FAILED_STATUSES",
    "alert_to_dict",
    "recent_alerts",
    "recent_traces",
    "record_alert_event",
    "record_run_trace",
    "record_trace",
    "trace_to_dict",
]
