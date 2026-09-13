from fastapi import APIRouter, Depends, Request
from app.config.settings import Settings
from app.schemas.tools import AgentRequest, ToolInvocation
from app.agents.coach_agent import AgentError, run_agent
from app.services.calendar_service import CalendarService, GoogleCalendarClient, build_calendar_tools
from app.services.strava_service import StravaClient, StravaService, build_strava_tools

router = APIRouter(prefix="/v1/agent", tags=["agent"])


def toolset(settings: Settings):
    strava = StravaService(StravaClient(settings.strava_access_token, base_url=settings.strava_api_base_url))
    calendar = CalendarService(GoogleCalendarClient(settings.google_calendar_access_token, calendar_id=settings.google_calendar_id, base_url=settings.google_calendar_api_base_url))
    return build_strava_tools(strava) + build_calendar_tools(calendar)


@router.get("/tools")
async def list_tools(settings: Settings = Depends(Settings.from_env)):
    tools = toolset(settings)
    return {"tools": [{"name": item.name, "description": item.description, "input_schema": item.args_schema.model_json_schema() if item.args_schema else {}} for item in tools]}


@router.post("/agent/chat")
async def chat(body: AgentRequest, settings: Settings = Depends(Settings.from_env)):
    return await run_agent(body.question, toolset(settings), api_key=settings.anthropic_api_key, model=settings.anthropic_model)
