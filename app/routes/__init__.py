from .health_routes import router as health_router
from .agent_routes import router as agent_router
from .calendar_routes import router as calendar_router
from .plan_routes import router as plan_router
from .session_routes import router as session_router
from .strava_routes import router as strava_router

__all__ = ["agent_router", "calendar_router", "health_router", "plan_router", "session_router", "strava_router"]
