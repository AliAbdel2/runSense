import time
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from app.config.settings import Settings
from app.db import get_db
from sqlalchemy.orm import Session
from app.services.strava_service import StravaClient, StravaError, StravaService, StravaInputError, DEFAULT_STREAMS

router = APIRouter(prefix="/v1/strava", tags=["strava"])


async def service(settings: Settings = Depends(Settings.from_env), db: Session = Depends(get_db)):
    client = StravaClient(settings.strava_access_token, base_url=settings.strava_api_base_url)
    try: yield StravaService(client, db=db)
    finally: await client.close()


@router.get("/athlete")
async def athlete(strava: StravaService = Depends(service)): return await strava.athlete()


@router.get("/activities")
async def activities(after: int | None = Query(None, ge=0), before: int | None = Query(None, ge=0), page: int = Query(1, ge=1), per_page: int = Query(100, ge=1, le=200), strava: StravaService = Depends(service)):
    return await strava.raw_activities(after=after, before=before, page=page, per_page=per_page)


@router.get("/training-history")
async def history(weeks: int = Query(4, ge=1, le=52), before: int | None = Query(None, ge=0), page: int = Query(1, ge=1), per_page: int = Query(100, ge=1, le=200), strava: StravaService = Depends(service)):
    end = before or int(time.time()); return await strava.training_history(max(0, end - weeks * 604800), before, page, per_page)


@router.get("/activities/{activity_id}")
async def activity(activity_id: int = Path(gt=0), include_all_efforts: bool = False, strava: StravaService = Depends(service)): return await strava.activity(activity_id, include_all_efforts)


@router.get("/activities/{activity_id}/streams")
async def streams(activity_id: int = Path(gt=0), keys: str = ",".join(DEFAULT_STREAMS), strava: StravaService = Depends(service)): return await strava.streams(activity_id, keys.split(","))


@router.get("/activities/{activity_id}/laps")
async def laps(activity_id: int = Path(gt=0), strava: StravaService = Depends(service)): return await strava.laps(activity_id)


@router.get("/zones")
async def zones(strava: StravaService = Depends(service)): return await strava.zones()


@router.get("/completed-run")
async def completed_run(session_start: datetime, expected_distance_m: float | None = Query(None, gt=0, le=200_000), max_time_delta_hours: float = Query(6, gt=0, le=24), strava: StravaService = Depends(service)): return await strava.verify_completed_run(session_start, expected_distance_m, max_time_delta_hours)
