from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.schemas.plan import PlanRequest
from app.services.plan_service import PlanService

router = APIRouter(prefix="/v1/plan", tags=["planning"])


@router.post("/plan")
def plan(body: PlanRequest, db: Session = Depends(get_db)):
    if body.source == "strava": raise ValueError("Strava planning is available through /v1/strava; use the authenticated history endpoint")
    return PlanService(db).create(week_start=body.week_start, scenario=body.scenario)
