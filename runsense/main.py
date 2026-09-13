import os
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .agent import Agent
from .evaluation import evaluate
from .models import CommitRequest, PlanRequest
from .store import Store
from .strava_mcp import StravaMCPError
from .strava_source import StravaSourceError

STATIC = Path(__file__).parent / "static"


def create_app(db_path: str | None = None) -> FastAPI:
    app = FastAPI(title="RunSense", version="0.1.0", docs_url="/api/docs", redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver", "[::1]"])
    agent = Agent(Store(db_path or os.getenv("RUNSENSE_DB", "data/runsense.sqlite3")))
    app.state.agent = agent
    # A fresh, same-origin browser session is required for personal data in demo mode.
    # This is local single-user protection, not a replacement for production login.
    personal_session = secrets.token_urlsafe(32)

    def require_personal_session(request: Request):
        cookie = request.cookies.get("runsense_personal", "")
        admin = os.getenv("RUNSENSE_ADMIN_TOKEN", "")
        bearer = request.headers.get("authorization", "")
        if not secrets.compare_digest(cookie, personal_session) and not (
            admin and secrets.compare_digest(bearer, f"Bearer {admin}")
        ):
            raise HTTPException(401, "Open the local RunSense dashboard first, or authenticate with the configured admin token.")

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
            return JSONResponse({"detail": "Cross-origin requests are disabled."}, status_code=403)
        if request.url.path.startswith("/api/") and os.getenv("RUNSENSE_MODE", "demo") == "live":
            # All live-mode endpoints are authenticated; do not leak authored logs through reads.
            if request.url.path not in ("/api/status", "/api/health"):
                token = os.getenv("RUNSENSE_ADMIN_TOKEN", "")
                if not token or not secrets.compare_digest(request.headers.get("authorization", ""), f"Bearer {token}"):
                    return JSONResponse({"detail": "Live mode requires a configured RUNSENSE_ADMIN_TOKEN and Bearer authorization."}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def live_mode():
        mode = os.getenv("RUNSENSE_MODE", "demo")
        if mode not in ("demo", "live"):
            raise HTTPException(503, "RUNSENSE_MODE must be demo or live.")
        return mode == "live"

    @app.exception_handler(ValueError)
    async def value_error(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(StravaMCPError)
    async def strava_error(_request, exc):
        return JSONResponse({"detail": str(exc), "provider": "strava_mcp"}, status_code=502)

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/status")
    async def status():
        live = live_mode()
        configurations = [
            ("Google Sheets", ["GOOGLE_ACCESS_TOKEN", "SHEETS_SPREADSHEET_ID"], "Athlete-authored training history"),
            ("Google Calendar", ["GOOGLE_ACCESS_TOKEN"], "Scheduled training sessions"),
            ("Notion", ["NOTION_API_KEY", "NOTION_DATA_SOURCE_ID"], "Plan journal and adaptation rationale"),
            ("ElevenLabs", ["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID"], "Optional coaching audio"),
        ]
        strava = agent.strava.status()
        return {"mode": "live" if live else "demo", "llm_configured": bool(os.getenv("ANTHROPIC_API_KEY") and os.getenv("ANTHROPIC_MODEL")),
                "integrations": [{"name": name, "status": "configured_unverified" if all(os.getenv(key) for key in keys) else "not_connected",
                                  "detail": detail + ("; simulated locally in demo mode" if not live else "; credentials need a live smoke test")}
                                 for name, keys, detail in configurations] + [
                                     {"name": "Strava MCP", "status": strava["status"], "detail": strava["detail"]}]}

    @app.get("/api/strava/status")
    async def strava_status(request: Request):
        require_personal_session(request)
        return agent.strava.status()

    @app.post("/api/strava/check")
    async def strava_check(request: Request):
        require_personal_session(request)
        async with agent.commit_lock:
            return await agent.strava.check()

    @app.post("/api/strava/disconnect")
    async def strava_disconnect(request: Request):
        require_personal_session(request)
        async with agent.commit_lock:
            return agent.strava.disconnect()

    @app.get("/api/demo")
    async def demo():
        return await agent.plan(PlanRequest())

    @app.post("/api/plan")
    async def plan(body: PlanRequest, request: Request):
        if body.source == "strava_mcp":
            require_personal_session(request)
        try:
            return await agent.plan(body, live=live_mode())
        except (ValueError, StravaMCPError):
            raise
        except Exception as exc:
            # IntegrationError implements safe string formatting; raw provider errors stay private.
            from .integrations import IntegrationError
            if isinstance(exc, IntegrationError):
                raise HTTPException(502, str(exc)) from exc
            raise HTTPException(502, "Planning failed. No app writes were requested.") from exc

    @app.post("/api/commit")
    async def commit(body: CommitRequest):
        if not live_mode():
            raise HTTPException(409, "Committing external actions is disabled in demo mode.")
        if not body.approved:
            raise HTTPException(400, "Review the saved preview, then set approved=true to commit that run.")
        try:
            return await agent.commit(body.run_id)
        except ValueError:
            raise
        except Exception as exc:
            raise HTTPException(502, "Commit stopped; earlier writes may remain. Read the run trace and retry the same run ID.") from exc

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str, request: Request):
        personal_result = agent.strava.get_preview(run_id)
        if personal_result:
            require_personal_session(request)
        result = personal_result or agent.store.get_run(run_id)
        if not result:
            raise HTTPException(404, "Run not found.")
        return agent.public(result)

    @app.post("/api/evaluate")
    async def run_evaluation():
        return await evaluate()

    @app.get("/")
    async def index():
        response = FileResponse(STATIC / "index.html")
        response.set_cookie("runsense_personal", personal_session, httponly=True, samesite="strict", max_age=3600)
        return response

    @app.get("/setup/strava-mcp", include_in_schema=False)
    async def strava_setup():
        return FileResponse(Path(__file__).parent.parent / "docs" / "strava-mcp.md", media_type="text/plain; charset=utf-8")

    app.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")
    return app


app = create_app()
