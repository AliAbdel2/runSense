from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from app.schemas.session import SampleBatch, SessionTimeRequest, StartSessionRequest, StravaUploadRequest
from app.services.session_service import LiveSessionManager, LiveSessionConflict, LiveSessionNotFound
from app.services.strava_service import StravaService
from app.services.strava_service import StravaClient

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


def manager(request: Request) -> LiveSessionManager: return request.app.state.live_sessions


@router.post("", status_code=201)
async def start(body: StartSessionRequest, sessions: LiveSessionManager = Depends(manager)): return await sessions.start(name=body.name, sport_type=body.sport_type, started_at=body.started_at)
@router.get("/{session_id}/live")
async def get_live(session_id: str, sessions=Depends(manager)): return await sessions.get(session_id)
@router.post("/{session_id}/samples")
async def samples(session_id: str, body: SampleBatch, sessions=Depends(manager)): return await sessions.add_samples(session_id, [item.model_dump() for item in body.samples])
@router.post("/{session_id}/pause")
async def pause(session_id: str, body: SessionTimeRequest, sessions=Depends(manager)): return await sessions.pause(session_id, body.at)
@router.post("/{session_id}/resume")
async def resume(session_id: str, body: SessionTimeRequest, sessions=Depends(manager)): return await sessions.resume(session_id, body.at)
@router.post("/{session_id}/finish")
async def finish(session_id: str, body: SessionTimeRequest, sessions=Depends(manager)): return await sessions.finish(session_id, body.at)
@router.get("/{session_id}/export.tcx")
async def export(session_id: str, sessions=Depends(manager)): return Response(await sessions.export_tcx(session_id), media_type="application/vnd.garmin.tcx+xml")


@router.post("/{session_id}/strava-upload")
async def upload(session_id: str, body: StravaUploadRequest, request: Request, sessions=Depends(manager)):
    if not body.owner_confirmed: raise LiveSessionConflict("Explicit owner confirmation is required before uploading to Strava")
    settings = request.app.state.settings
    client = StravaClient(settings.strava_access_token, base_url=settings.strava_api_base_url)
    try:
        tcx, metadata = await sessions.reserve_upload(session_id)
        if tcx is None: return {"reused": True, "upload": metadata}
        result = await StravaService(client).upload_tcx(tcx, external_id=f"runsense-{metadata['session_id']}", name=body.name or metadata["name"], description=body.description, trainer=body.trainer, commute=body.commute)
        data = result["data"]; upload_data = {"id": data.get("id"), "external_id": data.get("external_id"), "status": data.get("status"), "activity_id": data.get("activity_id"), "error": data.get("error"), "provider_status": result["meta"].get("provider_status")}
        return {"reused": False, "upload": upload_data, "live": await sessions.complete_upload(session_id, upload_data), "meta": result["meta"]}
    except Exception:
        await sessions.abort_upload(session_id); raise
    finally: await client.close()


@router.get("/{session_id}/strava-upload")
async def upload_status(session_id: str, sessions=Depends(manager)):
    live = await sessions.get(session_id)
    if not live.get("strava_upload"):
        raise LiveSessionConflict("This session has not been uploaded to Strava")
    return {"upload": live["strava_upload"], "live": live}


@router.websocket("/{session_id}/stream")
async def stream(websocket: WebSocket, session_id: str):
    sessions: LiveSessionManager = websocket.app.state.live_sessions
    queue = await sessions.subscribe(session_id); await websocket.accept()
    try:
        await websocket.send_json(await sessions.get(session_id))
        while True: await websocket.send_json(await queue.get())
    except WebSocketDisconnect: pass
    finally: await sessions.unsubscribe(session_id, queue)
