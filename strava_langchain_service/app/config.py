import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    strava_access_token: str = ""
    google_calendar_access_token: str = ""
    google_calendar_id: str = "primary"
    anthropic_api_key: str = ""
    anthropic_model: str = ""
    api_key: str = ""
    strava_api_base_url: str = "https://www.strava.com/api/v3"
    google_calendar_api_base_url: str = "https://www.googleapis.com/calendar/v3"

    @classmethod
    def from_env(cls):
        return cls(
            strava_access_token=os.getenv("STRAVA_ACCESS_TOKEN", ""),
            google_calendar_access_token=os.getenv(
                "GOOGLE_CALENDAR_ACCESS_TOKEN", os.getenv("GOOGLE_ACCESS_TOKEN", "")
            ),
            google_calendar_id=os.getenv("GOOGLE_CALENDAR_ID", cls.google_calendar_id),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            anthropic_model=os.getenv("ANTHROPIC_MODEL", ""),
            api_key=os.getenv("RUNSENSE_API_KEY", ""),
            strava_api_base_url=os.getenv("STRAVA_API_BASE_URL", cls.strava_api_base_url),
            google_calendar_api_base_url=os.getenv(
                "GOOGLE_CALENDAR_API_BASE_URL", cls.google_calendar_api_base_url
            ),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
