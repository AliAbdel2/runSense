from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Session as SessionRow


def get(db: Session, session_id: str): return db.get(SessionRow, session_id)


def upsert(db: Session, values: dict) -> SessionRow:
    row = db.get(SessionRow, values["id"])
    if row is None: row = SessionRow(**values); db.add(row)
    else:
        for key, value in values.items(): setattr(row, key, value)
    db.commit(); return row
