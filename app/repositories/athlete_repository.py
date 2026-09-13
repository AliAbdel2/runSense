from sqlalchemy.orm import Session
from app.models import Athlete


def get_or_create(db: Session, athlete_id="sara", name="Sara") -> Athlete:
    row = db.get(Athlete, athlete_id)
    if row is None:
        row = Athlete(id=athlete_id, name=name, guide_contacts=[], preferences={})
        db.add(row); db.commit(); db.refresh(row)
    return row
