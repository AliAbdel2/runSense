from fastapi import APIRouter, Depends, Path, Query
from app.config.settings import Settings
from app.services.calendar_service import CalendarService, CreateCalendarSessionInput, GoogleCalendarClient

router = APIRouter(prefix="/v1/calendar", tags=["calendar"])


async def service(settings: Settings = Depends(Settings.from_env)):
    client = GoogleCalendarClient(settings.google_calendar_access_token, calendar_id=settings.google_calendar_id, base_url=settings.google_calendar_api_base_url)
    try: yield CalendarService(client)
    finally: await client.close()


@router.post("/events")
async def create(body: CreateCalendarSessionInput, calendar: CalendarService = Depends(service)): return await calendar.create_session(**body.model_dump())
@router.get("/events/{event_id}")
async def get(event_id: str = Path(min_length=5, max_length=1024), calendar: CalendarService = Depends(service)): return await calendar.get_session(event_id)
@router.get("/events/{event_id}/guide")
async def guide(event_id: str = Path(min_length=5, max_length=1024), guide_email: str = Query(min_length=3, max_length=320), calendar: CalendarService = Depends(service)): return await calendar.check_guide(event_id, guide_email)
