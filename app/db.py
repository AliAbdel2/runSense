"""Database engine and session factory for the application package."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def database_url() -> str:
    value = os.getenv("RUNSENSE_DATABASE_URL") or os.getenv("DATABASE_URL")
    if value:
        return value
    path = os.getenv("RUNSENSE_DB", "data/runsense.sqlite3")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+pysqlite:///{path}"


def engine():
    return create_engine(database_url(), future=True, pool_pre_ping=True)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, future=True)


def configure_session_factory() -> None:
    SessionLocal.configure(bind=engine())


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
