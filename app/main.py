from __future__ import annotations

import secrets
import os
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config.settings import Settings
from app.db import Base, SessionLocal, configure_session_factory, engine
from app.middleware.auth import require_api_key
from app.models import Alert, Athlete, Activity, PlanWeek, Session, ToolTrace  # noqa: F401
from app.repositories.session_repository import upsert
from app.routes import agent_router, calendar_router, health_router, plan_router, session_router, strava_router
from app.services.session_service import LiveSessionConflict, LiveSessionManager, LiveSessionNotFound
from app.services.calendar_service import GoogleCalendarError, GoogleCalendarInputError
from app.services.strava_service import StravaError, StravaInputError


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if settings.database_url:
        os.environ["RUNSENSE_DATABASE_URL"] = settings.database_url
    configure_session_factory()
    Base.metadata.create_all(bind=engine())
    app = FastAPI(title="RunSense", version="2.0.0", docs_url="/api/docs")
    app.state.settings = settings
    app.dependency_overrides[Settings.from_env] = lambda: settings


    # TO BE REVIEWED: ---------------------------------------------------------
    def persist(snapshot):
        db = SessionLocal()
        try:
            started = datetime.fromisoformat(snapshot["started_at"].replace("Z", "+00:00"))
            ended = datetime.fromisoformat(snapshot["ended_at"].replace("Z", "+00:00")) if snapshot.get("ended_at") else None
            upsert(db, {"id": snapshot["session_id"], "athlete_id": "sara", "name": snapshot["name"], "sport_type": snapshot["sport_type"], "state": snapshot["state"], "started_at": started, "ended_at": ended, "summary_json": snapshot, "guide_status": "not_required"})
        finally: db.close()
    #--------------------------------------------------------------------------
    app.state.live_sessions = LiveSessionManager(persist=persist)

    @app.middleware("http")
    async def provider_auth(request: Request, call_next):
        if request.url.path.startswith("/v1/"):
            try:
                require_api_key(request)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return await call_next(request)
    app.include_router(health_router)
    app.include_router(agent_router)
    app.include_router(calendar_router)
    app.include_router(plan_router)
    app.include_router(strava_router)
    app.include_router(session_router)

    @app.exception_handler(StravaError)
    async def strava_error(_request, exc): return JSONResponse({"detail": exc.safe_message, "provider": "strava", "provider_status": exc.status_code}, status_code=422 if isinstance(exc, StravaInputError) else 502)
    @app.exception_handler(GoogleCalendarError)
    async def calendar_error(_request, exc): return JSONResponse({"detail": exc.safe_message, "provider": "google_calendar", "provider_status": exc.status_code}, status_code=422 if isinstance(exc, GoogleCalendarInputError) else 502)
    @app.exception_handler(LiveSessionNotFound)
    async def live_not_found(_request, exc): return JSONResponse({"detail": str(exc)}, status_code=404)
    @app.exception_handler(LiveSessionConflict)
    async def live_conflict(_request, exc): return JSONResponse({"detail": str(exc)}, status_code=409)
    @app.exception_handler(ValueError)
    async def value_error(_request, exc): return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/api/status")
    def status():
        return {"mode": "configured", "integrations": {"strava": bool(settings.strava_access_token), "google_calendar": bool(settings.google_calendar_access_token), "langchain": bool(settings.anthropic_api_key and settings.anthropic_model)}}

    return app


app = create_app()
