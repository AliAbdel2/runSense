import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    runsense_api_key: str = ""
    strava_access_token: str = ""
    strava_api_base_url: str = "https://www.strava.com/api/v3"
    google_calendar_access_token: str = ""
    google_calendar_id: str = "primary"
    google_calendar_api_base_url: str = "https://www.googleapis.com/calendar/v3"
    anthropic_api_key: str = ""
    anthropic_model: str = ""
    database_url: str = ""

    @classmethod
    def from_env(cls):
        return cls(
            runsense_api_key=os.getenv("RUNSENSE_API_KEY", ""),
            strava_access_token=os.getenv("STRAVA_ACCESS_TOKEN", ""),
            strava_api_base_url=os.getenv("STRAVA_API_BASE_URL", cls.strava_api_base_url),
            google_calendar_access_token=os.getenv("GOOGLE_CALENDAR_ACCESS_TOKEN", os.getenv("GOOGLE_ACCESS_TOKEN", "")),
            google_calendar_id=os.getenv("GOOGLE_CALENDAR_ID", cls.google_calendar_id),
            google_calendar_api_base_url=os.getenv("GOOGLE_CALENDAR_API_BASE_URL", cls.google_calendar_api_base_url),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            anthropic_model=os.getenv("ANTHROPIC_MODEL", ""),
            database_url=os.getenv("RUNSENSE_DATABASE_URL", os.getenv("DATABASE_URL", "")),
        )
