"""Typed SQLAlchemy schema stored in the same SQLite file as store.py (RUNSENSE_DB), in separate tables."""
import os
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session as OrmSession, mapped_column, sessionmaker

DEFAULT_DB_PATH = "data/runsense.sqlite3"


def _new_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    # Written as aware UTC; SQLite reads it back as naive UTC.
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Athlete(Base):
    __tablename__ = "athletes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    strava_token: Mapped[str | None] = mapped_column(String, nullable=True)
    calendar_token: Mapped[str | None] = mapped_column(String, nullable=True)
    guide_contacts: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    athlete_id: Mapped[str] = mapped_column(String, ForeignKey("athletes.id"), nullable=False)
    strava_id: Mapped[str | None] = mapped_column(String, nullable=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    km: Mapped[float] = mapped_column(Float, nullable=False)
    avg_pace: Mapped[str | None] = mapped_column(String, nullable=True)
    avg_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elevation: Mapped[float | None] = mapped_column(Float, nullable=True)


class PlanWeek(Base):
    __tablename__ = "plan_weeks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    athlete_id: Mapped[str] = mapped_column(String, ForeignKey("athletes.id"), nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    plan_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    plan_week_id: Mapped[str] = mapped_column(String, ForeignKey("plan_weeks.id"), nullable=False)
    calendar_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    guide_status: Mapped[str] = mapped_column(String, default="not_required", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    session_id: Mapped[str | None] = mapped_column(String, ForeignKey("sessions.id"), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    obj_class: Mapped[str] = mapped_column(String, nullable=False)
    zone: Mapped[str] = mapped_column(String, nullable=False)
    distance_bucket: Mapped[str] = mapped_column(String, nullable=False)
    tier: Mapped[str] = mapped_column(String, nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    spoken: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ToolTrace(Base):
    __tablename__ = "tool_traces"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True)  # cross-reference to store.py runs.id
    step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tool: Mapped[str] = mapped_column(String, nullable=False)
    input_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    output_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


def db_path(path: str | None = None) -> str:
    return path or os.getenv("RUNSENSE_DB", DEFAULT_DB_PATH)


def init_engine(path: str | None = None):
    """Create the engine, the parent directory and any missing typed tables."""
    resolved = db_path(path)
    Path(resolved).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite+pysqlite:///{resolved}", future=True)
    Base.metadata.create_all(engine)
    return engine


def get_session_factory(path: str | None = None) -> sessionmaker[OrmSession]:
    return sessionmaker(bind=init_engine(path), expire_on_commit=False, future=True)


# --- repository helpers -------------------------------------------------
# Plain synchronous functions, matching how store.py's sqlite3 calls are made
# from async request handlers today. Each takes an open SQLAlchemy session.


def get_or_create_athlete(session: OrmSession, athlete_id: str, name: str = "Sara",
                          guide_contacts: list | None = None, preferences: dict | None = None) -> Athlete:
    athlete = session.get(Athlete, athlete_id)
    if athlete is None:
        athlete = Athlete(id=athlete_id, name=name, guide_contacts=guide_contacts or [],
                          preferences=preferences or {})
        session.add(athlete)
        session.commit()
    return athlete


def record_alert(session: OrmSession, obj_class: str, zone: str, distance_bucket: str, tier: str,
                 session_id: str | None = None, latency_ms: float | None = None,
                 spoken: bool = False, ts: datetime | None = None) -> Alert:
    alert = Alert(session_id=session_id, obj_class=obj_class, zone=zone, distance_bucket=distance_bucket,
                  tier=tier, latency_ms=latency_ms, spoken=spoken, ts=ts or _utcnow())
    session.add(alert)
    session.commit()
    return alert


def list_alerts(session: OrmSession, session_id: str | None = None) -> list[Alert]:
    statement = select(Alert).order_by(Alert.ts, Alert.id)
    if session_id is not None:
        statement = statement.where(Alert.session_id == session_id)
    return list(session.scalars(statement))


def record_tool_trace(session: OrmSession, tool: str, step: int = 0, run_id: str | None = None,
                      input_json: dict | None = None, output_json: dict | None = None,
                      latency_ms: float | None = None, retries: int = 0,
                      error: str | None = None) -> ToolTrace:
    trace = ToolTrace(run_id=run_id, step=step, tool=tool, input_json=input_json or {},
                      output_json=output_json or {}, latency_ms=latency_ms, retries=retries, error=error)
    session.add(trace)
    session.commit()
    return trace


def list_tool_traces(session: OrmSession, run_id: str | None = None) -> list[ToolTrace]:
    statement = select(ToolTrace).order_by(ToolTrace.step, ToolTrace.created_at, ToolTrace.id)
    if run_id is not None:
        statement = statement.where(ToolTrace.run_id == run_id)
    return list(session.scalars(statement))


class TypedStore:
    """Session-free wrapper so callers can record rows with plain keyword args."""

    def __init__(self, path: str | None = None):
        self.path = db_path(path)
        self.session_factory = get_session_factory(self.path)

    @contextmanager
    def session(self):
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()

    def add(self, row):
        """Persist any typed row (Activity, PlanWeek, Session, ...) and return it detached."""
        with self.session() as session:
            session.add(row)
            session.commit()
        return row

    def get(self, model, row_id: str):
        with self.session() as session:
            return session.get(model, row_id)

    def get_or_create_athlete(self, athlete_id: str, **kwargs) -> Athlete:
        with self.session() as session:
            return get_or_create_athlete(session, athlete_id, **kwargs)

    def record_alert(self, **kwargs) -> Alert:
        with self.session() as session:
            return record_alert(session, **kwargs)

    def list_alerts(self, session_id: str | None = None) -> list[Alert]:
        with self.session() as session:
            return list_alerts(session, session_id)

    def record_tool_trace(self, **kwargs) -> ToolTrace:
        with self.session() as session:
            return record_tool_trace(session, **kwargs)

    def list_tool_traces(self, run_id: str | None = None) -> list[ToolTrace]:
        with self.session() as session:
            return list_tool_traces(session, run_id)
