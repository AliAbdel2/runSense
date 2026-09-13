"""LangChain tools and upload orchestration for live RunSense sessions."""

from __future__ import annotations

from datetime import datetime

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field

from .live_sessions import LiveSessionConflict, LiveSessionManager
from .service import StravaService


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartSessionInput(ToolInput):
    name: str = Field(default="RunSense Run", min_length=1, max_length=100)
    sport_type: str = Field(default="Run", pattern="^(Run|TrailRun|VirtualRun)$")
    started_at: datetime | None = None


class SessionInput(ToolInput):
    session_id: str | None = Field(default=None, min_length=1, max_length=100)


class FinishSessionInput(SessionInput):
    ended_at: datetime | None = None


class UploadSessionInput(SessionInput):
    owner_confirmed: bool = False
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    trainer: bool = False
    commute: bool = False


def _upload_record(data: dict, meta: dict) -> dict:
    return {
        "id": data.get("id"),
        "external_id": data.get("external_id"),
        "status": data.get("status"),
        "activity_id": data.get("activity_id"),
        "error": data.get("error"),
        "provider_status": meta.get("provider_status"),
    }


async def upload_finished_session(
    manager: LiveSessionManager,
    strava: StravaService,
    *,
    session_id: str | None,
    owner_confirmed: bool,
    name: str | None = None,
    description: str | None = None,
    trainer: bool = False,
    commute: bool = False,
) -> dict:
    if not owner_confirmed:
        raise LiveSessionConflict(
            "Explicit owner confirmation is required before uploading to Strava"
        )
    tcx, session = await manager.reserve_upload(session_id)
    if tcx is None:
        return {"reused": True, "upload": session}
    try:
        result = await strava.upload_tcx(
            tcx,
            external_id=f"runsense-{session['session_id']}",
            name=name or session["name"],
            description=description,
            trainer=trainer,
            commute=commute,
        )
    except Exception:
        await manager.abort_upload(session["session_id"])
        raise
    upload = _upload_record(result["data"], result["meta"])
    live = await manager.complete_upload(session["session_id"], upload)
    return {"reused": False, "upload": upload, "live": live, "meta": result["meta"]}


async def refresh_upload_status(
    manager: LiveSessionManager,
    strava: StravaService,
    session_id: str,
) -> dict:
    live = await manager.get(session_id)
    upload = live.get("strava_upload")
    if not upload:
        raise LiveSessionConflict("This session has not been uploaded to Strava")
    upload_id = upload.get("id")
    if not isinstance(upload_id, int) or upload_id < 1:
        raise LiveSessionConflict("Strava did not return a valid upload identifier")
    result = await strava.upload_status(upload_id)
    updated = _upload_record(result["data"], result["meta"])
    snapshot = await manager.update_upload(session_id, updated)
    return {"upload": updated, "live": snapshot, "meta": result["meta"]}


def build_live_tools(
    manager: LiveSessionManager, strava: StravaService
) -> list[BaseTool]:
    @tool("runsense_start_session", args_schema=StartSessionInput)
    async def start_session(
        name: str = "RunSense Run",
        sport_type: str = "Run",
        started_at: datetime | None = None,
    ) -> dict:
        """Start a live RunSense GPS session; this does not start or write anything in Strava."""
        return await manager.start(name=name, sport_type=sport_type, started_at=started_at)

    @tool("runsense_get_live_metrics", args_schema=SessionInput)
    async def get_live_metrics(session_id: str | None = None) -> dict:
        """Get live metrics for spoken feedback; omit session_id to use the most recent run."""
        return await manager.get(session_id)

    @tool("runsense_finish_session", args_schema=FinishSessionInput)
    async def finish_session(
        session_id: str | None = None, ended_at: datetime | None = None
    ) -> dict:
        """Finish the latest RunSense session without uploading it; a session ID is optional."""
        return await manager.finish(session_id, ended_at)

    @tool("runsense_upload_session_to_strava", args_schema=UploadSessionInput)
    async def upload_session_to_strava(
        session_id: str | None = None,
        owner_confirmed: bool = False,
        name: str | None = None,
        description: str | None = None,
        trainer: bool = False,
        commute: bool = False,
    ) -> dict:
        """Upload the latest finished TCX only after the owner's current command explicitly confirms it."""
        return await upload_finished_session(
            manager,
            strava,
            session_id=session_id,
            owner_confirmed=owner_confirmed,
            name=name,
            description=description,
            trainer=trainer,
            commute=commute,
        )

    return [start_session, get_live_metrics, finish_session, upload_session_to_strava]
