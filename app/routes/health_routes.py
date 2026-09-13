from fastapi import APIRouter, Depends
from app.config.settings import Settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health(settings: Settings = Depends(Settings.from_env)):
    return {"status": "ok", "strava_configured": bool(settings.strava_access_token), "calendar_configured": bool(settings.google_calendar_access_token), "langchain_configured": bool(settings.anthropic_api_key and settings.anthropic_model)}
