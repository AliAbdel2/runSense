"""FastAPI surface for Postman and the LangChain Strava tools."""

from __future__ import annotations

import secrets
import time
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .agent import AgentError, run_agent
from .config import Settings
from .service import DEFAULT_STREAMS, StravaService
from .strava_client import StravaAPIError, StravaClient, StravaInputError
from .tools import build_strava_tools


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolInvocation(StrictModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentRequest(StrictModel):
    question: str = Field(min_length=1, max_length=1000)


def create_app(
    *,
    settings: Settings | None = None,
    client_factory: Callable[..., StravaClient] = StravaClient,
) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(
        title="RunSense Strava LangChain Service",
        version="1.0.0",
        docs_url="/docs",
        redoc_url=None,
    )

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

    @app.exception_handler(AgentError)
    async def agent_error(_request: Request, exc: AgentError):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "strava_configured": bool(settings.strava_access_token),
            "langchain_configured": bool(settings.anthropic_api_key and settings.anthropic_model),
        }

    @app.get("/v1/tools")
    async def list_tools(request: Request, strava: StravaService = Depends(service)):
        authorize(request)
        tools = build_strava_tools(strava)
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
    ):
        tools = {item.name: item for item in build_strava_tools(strava)}
        selected = tools.get(tool_name)
        if selected is None:
            raise HTTPException(404, "Unknown tool")
        try:
            result = await selected.ainvoke(body.arguments)
        except ValidationError as exc:
            raise HTTPException(422, detail=exc.errors(include_url=False)) from exc
        return {"tool": tool_name, "result": result}

    @app.post("/v1/agent/chat")
    async def agent_chat(body: AgentRequest, strava: StravaService = Depends(service)):
        return await run_agent(
            body.question,
            build_strava_tools(strava),
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

    return app


app = create_app()
