"""Small read-only async client for the approved Strava REST integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import httpx


T = TypeVar("T")


class StravaAPIError(RuntimeError):
    """Provider error whose public message never contains tokens or response bodies."""

    def __init__(self, message: str, status_code: int | None = None):
        self.safe_message = message
        self.status_code = status_code
        suffix = f" (provider status {status_code})" if status_code else ""
        super().__init__(message + suffix)


class StravaInputError(StravaAPIError):
    """Caller supplied an invalid ID, range, or stream key."""


@dataclass(frozen=True)
class ProviderResponse(Generic[T]):
    data: T
    status_code: int
    rate_limits: dict[str, dict[str, int | None]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "data": self.data,
            "meta": {"provider_status": self.status_code, "rate_limits": self.rate_limits},
        }


def _pair(value: str | None) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    try:
        first, second = value.split(",", maxsplit=1)
        return int(first), int(second)
    except (ValueError, TypeError):
        return None, None


def _rate_limits(headers: httpx.Headers) -> dict[str, dict[str, int | None]]:
    overall_limit = _pair(headers.get("X-RateLimit-Limit"))
    overall_usage = _pair(headers.get("X-RateLimit-Usage"))
    read_limit = _pair(headers.get("X-ReadRateLimit-Limit"))
    read_usage = _pair(headers.get("X-ReadRateLimit-Usage"))

    def bucket(limit: tuple[int | None, int | None], usage: tuple[int | None, int | None]):
        return {
            "limit_15_min": limit[0],
            "limit_daily": limit[1],
            "used_15_min": usage[0],
            "used_daily": usage[1],
        }

    return {"overall": bucket(overall_limit, overall_usage), "read": bucket(read_limit, read_usage)}


class StravaClient:
    max_attempts = 4

    def __init__(
        self,
        access_token: str,
        *,
        base_url: str = "https://www.strava.com/api/v3",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not access_token.strip():
            raise StravaAPIError("STRAVA_ACCESS_TOKEN is not configured")
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            transport=transport,
            timeout=15,
            headers={
                "Authorization": f"Bearer {access_token.strip()}",
                "Accept": "application/json",
                "User-Agent": "RunSense-Strava-Agent/1.0",
            },
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def close(self):
        await self._client.aclose()

    async def _get(self, path: str, *, params=None, expected: type[dict] | type[list]):
        for attempt in range(self.max_attempts):
            try:
                response = await self._client.get(path, params=params)
            except httpx.HTTPError as exc:
                raise StravaAPIError("Strava request failed") from exc
            if (response.status_code == 429 or response.status_code >= 500) and attempt < self.max_attempts - 1:
                try:
                    delay = float(response.headers.get("Retry-After", 0.1 * 2**attempt))
                except ValueError:
                    delay = 0.1 * 2**attempt
                await asyncio.sleep(min(max(delay, 0), 2))
                continue
            if response.status_code >= 400:
                message = "Strava authentication failed" if response.status_code in (401, 403) else "Strava request failed"
                raise StravaAPIError(message, response.status_code)
            try:
                body = response.json()
            except ValueError as exc:
                raise StravaAPIError("Strava returned invalid JSON", response.status_code) from exc
            if not isinstance(body, expected):
                raise StravaAPIError("Strava returned an unexpected response shape", response.status_code)
            return ProviderResponse(body, response.status_code, _rate_limits(response.headers))
        raise StravaAPIError("Strava request failed")

    async def get_athlete(self):
        return await self._get("/athlete", expected=dict)

    async def list_activities(
        self,
        *,
        after: int | None = None,
        before: int | None = None,
        page: int = 1,
        per_page: int = 100,
    ):
        if page < 1 or not 1 <= per_page <= 200:
            raise StravaInputError("page must be positive and per_page must be between 1 and 200")
        if after is not None and before is not None and after >= before:
            raise StravaInputError("after must be earlier than before")
        params = {"page": page, "per_page": per_page}
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before
        return await self._get("/athlete/activities", params=params, expected=list)

    async def get_activity(self, activity_id: int, include_all_efforts: bool = False):
        if activity_id < 1:
            raise StravaInputError("activity_id must be positive")
        return await self._get(
            f"/activities/{activity_id}",
            params={"include_all_efforts": str(include_all_efforts).lower()},
            expected=dict,
        )

    async def get_laps(self, activity_id: int):
        if activity_id < 1:
            raise StravaInputError("activity_id must be positive")
        return await self._get(f"/activities/{activity_id}/laps", expected=list)

    async def get_streams(self, activity_id: int, keys: list[str]):
        if activity_id < 1:
            raise StravaInputError("activity_id must be positive")
        return await self._get(
            f"/activities/{activity_id}/streams",
            params={"keys": ",".join(keys), "key_by_type": "true"},
            expected=dict,
        )

    async def get_zones(self):
        return await self._get("/athlete/zones", expected=dict)
