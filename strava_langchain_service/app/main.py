"""FastAPI surface for RunSense's LangChain integration tools."""

from __future__ import annotations

import secrets
import time
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Path,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .agent import AgentError, run_agent
from .calendar_client import GoogleCalendarClient, GoogleCalendarError, GoogleCalendarInputError
from .calendar_service import CalendarService
from .calendar_tools import (
    CreateCalendarSessionInput,
    build_calendar_tools,
)
from .config import Settings
from .live_sessions import LiveSessionConflict, LiveSessionManager, LiveSessionNotFound
from .live_tools import build_live_tools, refresh_upload_status, upload_finished_session
from .service import DEFAULT_STREAMS, StravaService
from .strava_client import StravaAPIError, StravaClient, StravaInputError
from .tools import build_strava_tools


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolInvocation(StrictModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentRequest(StrictModel):
    question: str = Field(min_length=1, max_length=1000)


class StartSessionRequest(StrictModel):
    name: str = Field(default="RunSense Run", min_length=1, max_length=100)
    sport_type: str = Field(default="Run", pattern="^(Run|TrailRun|VirtualRun)$")
    started_at: datetime | None = None


class LocationSample(StrictModel):
    timestamp: datetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(default=10, gt=0, le=10_000)
    altitude_m: float | None = Field(default=None, ge=-500, le=10_000)
    heart_rate_bpm: int | None = Field(default=None, ge=20, le=250)
    cadence_spm: int | None = Field(default=None, ge=0, le=300)


class SampleBatch(StrictModel):
    samples: list[LocationSample] = Field(min_length=1, max_length=200)


class SessionTimeRequest(StrictModel):
    at: datetime | None = None


class StravaUploadRequest(StrictModel):
    owner_confirmed: bool = False
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    trainer: bool = False
    commute: bool = False


def create_app(
    *,
    settings: Settings | None = None,
    client_factory: Callable[..., StravaClient] = StravaClient,
    calendar_client_factory: Callable[..., GoogleCalendarClient] = GoogleCalendarClient,
) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(
        title="RunSense Strava + Calendar LangChain Service",
        version="1.2.0",
        docs_url="/docs",
        redoc_url=None,
    )
    live_sessions = LiveSessionManager()
    app.state.live_sessions = live_sessions

    def authorize(request: Request):
        if not settings.api_key:
            raise HTTPException(503, "RUNSENSE_API_KEY is not configured")
        if not secrets.compare_digest(
            request.headers.get("authorization", ""), f"Bearer {settings.api_key}"
        ):
            raise HTTPException(401, "Missing or invalid RunSense API key")

    async def service(request: Request) -> AsyncIterator[StravaService]:
        authorize(request)
        client = client_factory(
            settings.strava_access_token, base_url=settings.strava_api_base_url
        )
        try:
            yield StravaService(client)
        finally:
            await client.close()

    async def calendar_service(request: Request) -> AsyncIterator[CalendarService]:
        authorize(request)
        client = calendar_client_factory(
            settings.google_calendar_access_token,
            calendar_id=settings.google_calendar_id,
            base_url=settings.google_calendar_api_base_url,
        )
        try:
            yield CalendarService(client)
        finally:
            await client.close()

    @app.exception_handler(StravaAPIError)
    async def strava_error(_request: Request, exc: StravaAPIError):
        return JSONResponse(
            {
                "detail": exc.safe_message,
                "provider": "strava",
                "provider_status": exc.status_code,
            },
            status_code=503 if exc.status_code is None else 502,
        )

    @app.exception_handler(StravaInputError)
    async def strava_input_error(_request: Request, exc: StravaInputError):
        return JSONResponse({"detail": exc.safe_message}, status_code=422)

    @app.exception_handler(GoogleCalendarError)
    async def calendar_error(_request: Request, exc: GoogleCalendarError):
        return JSONResponse(
            {
                "detail": exc.safe_message,
                "provider": "google_calendar",
                "provider_status": exc.status_code,
            },
            status_code=503 if exc.status_code is None else 502,
        )

    @app.exception_handler(GoogleCalendarInputError)
    async def calendar_input_error(_request: Request, exc: GoogleCalendarInputError):
        return JSONResponse({"detail": exc.safe_message}, status_code=422)

    @app.exception_handler(AgentError)
    async def agent_error(_request: Request, exc: AgentError):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.exception_handler(LiveSessionNotFound)
    async def live_not_found(_request: Request, exc: LiveSessionNotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(LiveSessionConflict)
    async def live_conflict(_request: Request, exc: LiveSessionConflict):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "strava_configured": bool(settings.strava_access_token),
            "google_calendar_configured": bool(settings.google_calendar_access_token),
            "langchain_configured": bool(settings.anthropic_api_key and settings.anthropic_model),
            "live_sessions": "in_memory",
        }

    def all_tools(strava: StravaService, calendar: CalendarService):
        return (
            build_strava_tools(strava)
            + build_calendar_tools(calendar)
            + build_live_tools(live_sessions, strava)
        )

    @app.get("/v1/tools")
    async def list_tools(
        request: Request,
        strava: StravaService = Depends(service),
        calendar: CalendarService = Depends(calendar_service),
    ):
        authorize(request)
        tools = all_tools(strava, calendar)
        return {
            "tools": [
                {
                    "name": item.name,
                    "description": item.description,
                    "input_schema": item.args_schema.model_json_schema() if item.args_schema else {},
                }
                for item in tools
            ]
        }

    @app.post("/v1/tools/{tool_name}/invoke")
    async def invoke_tool(
        tool_name: str,
        body: ToolInvocation,
        strava: StravaService = Depends(service),
        calendar: CalendarService = Depends(calendar_service),
    ):
        tools = {item.name: item for item in all_tools(strava, calendar)}
        selected = tools.get(tool_name)
        if selected is None:
            raise HTTPException(404, "Unknown tool")
        try:
            result = await selected.ainvoke(body.arguments)
        except ValidationError as exc:
            raise HTTPException(422, detail=exc.errors(include_url=False)) from exc
        return {"tool": tool_name, "result": result}

    @app.post("/v1/agent/chat")
    async def agent_chat(
        body: AgentRequest,
        strava: StravaService = Depends(service),
        calendar: CalendarService = Depends(calendar_service),
    ):
        return await run_agent(
            body.question,
            all_tools(strava, calendar),
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
        )

    @app.get("/v1/strava/athlete")
    async def athlete(strava: StravaService = Depends(service)):
        return await strava.athlete()

    @app.get("/v1/strava/activities")
    async def activities(
        after: int | None = Query(default=None, ge=0),
        before: int | None = Query(default=None, ge=0),
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=100, ge=1, le=200),
        strava: StravaService = Depends(service),
    ):
        return await strava.raw_activities(after, before, page, per_page)

    @app.get("/v1/strava/training-history")
    async def training_history(
        weeks: int = Query(default=4, ge=1, le=52),
        before: int | None = Query(default=None, ge=0),
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=100, ge=1, le=200),
        strava: StravaService = Depends(service),
    ):
        end = before or int(time.time())
        after = max(0, end - weeks * 7 * 24 * 60 * 60)
        return await strava.training_history(after, before, page, per_page)

    @app.get("/v1/strava/activities/{activity_id}")
    async def activity(
        activity_id: int = Path(gt=0),
        include_all_efforts: bool = False,
        strava: StravaService = Depends(service),
    ):
        return await strava.activity(activity_id, include_all_efforts)

    @app.get("/v1/strava/activities/{activity_id}/laps")
    async def laps(
        activity_id: int = Path(gt=0), strava: StravaService = Depends(service)
    ):
        return await strava.laps(activity_id)

    @app.get("/v1/strava/activities/{activity_id}/streams")
    async def streams(
        activity_id: int = Path(gt=0),
        keys: str = ",".join(DEFAULT_STREAMS),
        strava: StravaService = Depends(service),
    ):
        return await strava.streams(activity_id, keys.split(","))

    @app.get("/v1/strava/zones")
    async def zones(strava: StravaService = Depends(service)):
        return await strava.zones()

    @app.get("/v1/strava/completed-run")
    async def completed_run(
        session_start: datetime,
        expected_distance_m: float | None = Query(default=None, gt=0, le=200_000),
        max_time_delta_hours: float = Query(default=6, gt=0, le=24),
        strava: StravaService = Depends(service),
    ):
        return await strava.verify_completed_run(
            session_start, expected_distance_m, max_time_delta_hours
        )

    @app.post("/v1/calendar/events")
    async def create_calendar_event(
        body: CreateCalendarSessionInput,
        calendar: CalendarService = Depends(calendar_service),
    ):
        return await calendar.create_session(**body.model_dump())

    @app.get("/v1/calendar/events/{event_id}")
    async def get_calendar_event(
        event_id: str = Path(min_length=5, max_length=1024),
        calendar: CalendarService = Depends(calendar_service),
    ):
        return await calendar.get_session(event_id)

    @app.get("/v1/calendar/events/{event_id}/guide")
    async def get_calendar_guide_status(
        event_id: str = Path(min_length=5, max_length=1024),
        guide_email: str = Query(min_length=3, max_length=320),
        calendar: CalendarService = Depends(calendar_service),
    ):
        return await calendar.check_guide(event_id, guide_email)

    @app.post("/v1/sessions", status_code=201)
    async def start_live_session(body: StartSessionRequest, request: Request):
        authorize(request)
        return await live_sessions.start(
            name=body.name,
            sport_type=body.sport_type,
            started_at=body.started_at,
        )

    @app.get("/v1/sessions/{session_id}/live")
    async def get_live_session(session_id: str, request: Request):
        authorize(request)
        return await live_sessions.get(session_id)

    @app.post("/v1/sessions/{session_id}/samples")
    async def add_live_samples(session_id: str, body: SampleBatch, request: Request):
        authorize(request)
        return await live_sessions.add_samples(
            session_id, [sample.model_dump() for sample in body.samples]
        )

    @app.post("/v1/sessions/{session_id}/pause")
    async def pause_live_session(session_id: str, body: SessionTimeRequest, request: Request):
        authorize(request)
        return await live_sessions.pause(session_id, body.at)

    @app.post("/v1/sessions/{session_id}/resume")
    async def resume_live_session(session_id: str, body: SessionTimeRequest, request: Request):
        authorize(request)
        return await live_sessions.resume(session_id, body.at)

    @app.post("/v1/sessions/{session_id}/finish")
    async def finish_live_session(session_id: str, body: SessionTimeRequest, request: Request):
        authorize(request)
        return await live_sessions.finish(session_id, body.at)

    @app.get("/v1/sessions/{session_id}/export.tcx")
    async def export_live_session(session_id: str, request: Request):
        authorize(request)
        content = await live_sessions.export_tcx(session_id)
        return Response(
            content=content,
            media_type="application/vnd.garmin.tcx+xml",
            headers={"Content-Disposition": f'attachment; filename="runsense-{session_id}.tcx"'},
        )

    @app.post("/v1/sessions/{session_id}/strava-upload")
    async def upload_live_session(
        session_id: str,
        body: StravaUploadRequest,
        strava: StravaService = Depends(service),
    ):
        return await upload_finished_session(
            live_sessions,
            strava,
            session_id=session_id,
            owner_confirmed=body.owner_confirmed,
            name=body.name,
            description=body.description,
            trainer=body.trainer,
            commute=body.commute,
        )

    @app.get("/v1/sessions/{session_id}/strava-upload")
    async def get_live_session_upload(
        session_id: str,
        strava: StravaService = Depends(service),
    ):
        return await refresh_upload_status(live_sessions, strava, session_id)

    @app.websocket("/v1/sessions/{session_id}/stream")
    async def live_session_stream(websocket: WebSocket, session_id: str):
        expected = f"Bearer {settings.api_key}"
        if not settings.api_key or not secrets.compare_digest(
            websocket.headers.get("authorization", ""), expected
        ):
            await websocket.close(code=4401)
            return
        try:
            queue = await live_sessions.subscribe(session_id)
        except LiveSessionNotFound:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        try:
            await websocket.send_json(await live_sessions.get(session_id))
            while True:
                await websocket.send_json(await queue.get())
        except WebSocketDisconnect:
            pass
        finally:
            await live_sessions.unsubscribe(session_id, queue)

    return app


app = create_app()
