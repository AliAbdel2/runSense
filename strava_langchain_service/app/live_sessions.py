"""In-memory live run tracking with deterministic GPS metrics and TCX export.

Persistence is deliberately behind this small manager because the main RunSense
database architecture will be integrated later.  The API contract and TCX export
do not depend on the eventual database implementation.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from xml.etree import ElementTree as ET


SessionState = Literal["active", "paused", "finished"]
MAX_POINTS_PER_SESSION = 100_000
MAX_RUNNING_SPEED_MPS = 12.5
MAX_GPS_ACCURACY_M = 50.0
MIN_DISTANCE_FOR_PACE_M = 5.0
PACE_WINDOW_SECONDS = 10.0


class LiveSessionError(RuntimeError):
    """Safe, user-facing live-session error."""


class LiveSessionNotFound(LiveSessionError):
    pass


class LiveSessionConflict(LiveSessionError):
    pass


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return utc(value).isoformat().replace("+00:00", "Z")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius_m * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def pace_text(seconds_per_km: float | None) -> str | None:
    if seconds_per_km is None:
        return None
    rounded = max(0, round(seconds_per_km))
    minutes, seconds = divmod(rounded, 60)
    minute_word = "minute" if minutes == 1 else "minutes"
    if seconds == 0:
        return f"{minutes} {minute_word} per kilometre"
    second_word = "second" if seconds == 1 else "seconds"
    return f"{minutes} {minute_word} {seconds} {second_word} per kilometre"


@dataclass
class LocationPoint:
    timestamp: datetime
    latitude: float
    longitude: float
    accuracy_m: float
    altitude_m: float | None
    heart_rate_bpm: int | None
    cadence_spm: int | None
    distance_m: float
    speed_mps: float | None
    track_index: int


@dataclass
class LiveSession:
    id: str
    name: str
    sport_type: str
    started_at: datetime
    state: SessionState = "active"
    ended_at: datetime | None = None
    paused_at: datetime | None = None
    paused_seconds: float = 0.0
    track_index: int = 0
    track_started_at: datetime | None = None
    points: list[LocationPoint] = field(default_factory=list)
    rejected_samples: int = 0
    strava_upload: dict[str, Any] | None = None
    upload_in_progress: bool = False

    def __post_init__(self):
        if self.track_started_at is None:
            self.track_started_at = self.started_at

    def active_elapsed_seconds(self, as_of: datetime | None = None) -> float:
        end = self.ended_at or as_of or (
            self.points[-1].timestamp if self.points else datetime.now(timezone.utc)
        )
        end = max(utc(end), self.started_at)
        paused = self.paused_seconds
        if self.paused_at is not None:
            paused += max(0.0, (end - self.paused_at).total_seconds())
        return max(0.0, (end - self.started_at).total_seconds() - paused)

    def current_pace_seconds_per_km(self) -> float | None:
        if self.state != "active" or len(self.points) < 2:
            return None
        latest = self.points[-1]
        candidates = [
            point
            for point in reversed(self.points)
            if point.track_index == latest.track_index
            and (latest.timestamp - point.timestamp).total_seconds() <= PACE_WINDOW_SECONDS
        ]
        candidates.reverse()
        if len(candidates) < 2:
            return None
        seconds = (candidates[-1].timestamp - candidates[0].timestamp).total_seconds()
        distance = candidates[-1].distance_m - candidates[0].distance_m
        if seconds <= 0 or distance < MIN_DISTANCE_FOR_PACE_M:
            return None
        return seconds * 1000 / distance

    def snapshot(self) -> dict[str, Any]:
        distance = self.points[-1].distance_m if self.points else 0.0
        as_of = self.ended_at or (self.points[-1].timestamp if self.points else None)
        elapsed = self.active_elapsed_seconds(as_of)
        current_pace = self.current_pace_seconds_per_km()
        average_pace = elapsed * 1000 / distance if distance >= MIN_DISTANCE_FOR_PACE_M else None
        latest = self.points[-1] if self.points else None
        spoken_pace = pace_text(current_pace)
        if distance < 1000:
            spoken_distance = f"{round(distance)} metres"
        else:
            spoken_distance = f"{distance / 1000:.2f} kilometres"
        spoken_status = (
            f"Current pace is {spoken_pace}. Distance is {spoken_distance}."
            if spoken_pace
            else f"Current pace is not available yet. Distance is {spoken_distance}."
        )
        return {
            "session_id": self.id,
            "name": self.name,
            "sport_type": self.sport_type,
            "state": self.state,
            "started_at": iso(self.started_at),
            "ended_at": iso(self.ended_at),
            "active_elapsed_seconds": round(elapsed, 1),
            "distance_m": round(distance, 2),
            "distance_km": round(distance / 1000, 3),
            "current_pace_seconds_per_km": round(current_pace, 1) if current_pace else None,
            "current_pace_spoken": spoken_pace,
            "average_pace_seconds_per_km": round(average_pace, 1) if average_pace else None,
            "average_pace_spoken": pace_text(average_pace),
            "heart_rate_bpm": latest.heart_rate_bpm if latest else None,
            "cadence_spm": latest.cadence_spm if latest else None,
            "spoken_status": spoken_status,
            "accepted_samples": len(self.points),
            "rejected_samples": self.rejected_samples,
            "strava_upload": self.strava_upload,
        }


class LiveSessionManager:
    """Concurrency-safe session state; replace storage internals at DB integration time."""

    def __init__(self):
        self._sessions: dict[str, LiveSession] = {}
        self._lock = asyncio.Lock()
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    async def start(
        self,
        *,
        name: str,
        sport_type: str,
        started_at: datetime | None = None,
    ) -> dict[str, Any]:
        session = LiveSession(
            id=str(uuid.uuid4()),
            name=name.strip(),
            sport_type=sport_type,
            started_at=utc(started_at or datetime.now(timezone.utc)),
        )
        async with self._lock:
            self._sessions[session.id] = session
        await self._publish(session)
        return session.snapshot()

    def _require(self, session_id: str | None) -> LiveSession:
        if session_id is None:
            session = next(reversed(self._sessions.values()), None)
        else:
            session = self._sessions.get(session_id)
        if session is None:
            raise LiveSessionNotFound("Live session not found")
        return session

    async def get(self, session_id: str | None = None) -> dict[str, Any]:
        async with self._lock:
            return self._require(session_id).snapshot()

    async def add_samples(self, session_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        results = []
        async with self._lock:
            session = self._require(session_id)
            if session.state != "active":
                raise LiveSessionConflict("GPS samples are accepted only while the session is active")
            for row in rows:
                results.append(self._add_sample(session, row))
            snapshot = session.snapshot()
        await self._publish_snapshot(session_id, snapshot)
        return {"samples": results, "live": snapshot}

    def _add_sample(self, session: LiveSession, row: dict[str, Any]) -> dict[str, Any]:
        if len(session.points) >= MAX_POINTS_PER_SESSION:
            raise LiveSessionConflict("Session sample limit reached")
        timestamp = utc(row["timestamp"])
        accuracy = float(row["accuracy_m"])
        if timestamp < (session.track_started_at or session.started_at):
            session.rejected_samples += 1
            return {"accepted": False, "reason": "sample_before_active_segment"}
        if accuracy > MAX_GPS_ACCURACY_M:
            session.rejected_samples += 1
            return {"accepted": False, "reason": "gps_accuracy_too_low"}

        previous = session.points[-1] if session.points else None
        distance = previous.distance_m if previous else 0.0
        speed = None
        if previous and previous.track_index == session.track_index:
            seconds = (timestamp - previous.timestamp).total_seconds()
            if seconds <= 0:
                session.rejected_samples += 1
                return {"accepted": False, "reason": "timestamp_not_increasing"}
            segment = haversine_m(
                previous.latitude,
                previous.longitude,
                float(row["latitude"]),
                float(row["longitude"]),
            )
            speed = segment / seconds
            if speed > MAX_RUNNING_SPEED_MPS:
                session.rejected_samples += 1
                return {"accepted": False, "reason": "implausible_running_speed"}
            # Ignore sub-metre GPS drift while stationary without discarding the sample.
            if segment >= 1.5:
                distance += segment

        point = LocationPoint(
            timestamp=timestamp,
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            accuracy_m=accuracy,
            altitude_m=row.get("altitude_m"),
            heart_rate_bpm=row.get("heart_rate_bpm"),
            cadence_spm=row.get("cadence_spm"),
            distance_m=distance,
            speed_mps=speed,
            track_index=session.track_index,
        )
        session.points.append(point)
        return {
            "accepted": True,
            "timestamp": iso(timestamp),
            "distance_m": round(distance, 2),
        }

    async def pause(self, session_id: str, at: datetime | None = None) -> dict[str, Any]:
        async with self._lock:
            session = self._require(session_id)
            if session.state != "active":
                raise LiveSessionConflict("Only an active session can be paused")
            paused_at = utc(at or datetime.now(timezone.utc))
            if paused_at < session.started_at or (
                session.points and paused_at < session.points[-1].timestamp
            ):
                raise LiveSessionConflict("Pause time cannot precede recorded session data")
            session.paused_at = paused_at
            session.state = "paused"
            snapshot = session.snapshot()
        await self._publish_snapshot(session_id, snapshot)
        return snapshot

    async def resume(self, session_id: str, at: datetime | None = None) -> dict[str, Any]:
        async with self._lock:
            session = self._require(session_id)
            if session.state != "paused" or session.paused_at is None:
                raise LiveSessionConflict("Only a paused session can be resumed")
            resumed_at = utc(at or datetime.now(timezone.utc))
            if resumed_at < session.paused_at:
                raise LiveSessionConflict("Resume time cannot precede pause time")
            session.paused_seconds += (resumed_at - session.paused_at).total_seconds()
            session.paused_at = None
            session.track_index += 1
            session.track_started_at = resumed_at
            session.state = "active"
            snapshot = session.snapshot()
        await self._publish_snapshot(session_id, snapshot)
        return snapshot

    async def finish(self, session_id: str | None, at: datetime | None = None) -> dict[str, Any]:
        async with self._lock:
            session = self._require(session_id)
            if session.state == "finished":
                return session.snapshot()
            finished_at = utc(at or datetime.now(timezone.utc))
            if session.paused_at is not None:
                if finished_at < session.paused_at:
                    raise LiveSessionConflict("Finish time cannot precede pause time")
                session.paused_seconds += (finished_at - session.paused_at).total_seconds()
                session.paused_at = None
            if finished_at < session.started_at:
                raise LiveSessionConflict("Finish time cannot precede session start")
            if session.points and finished_at < session.points[-1].timestamp:
                raise LiveSessionConflict("Finish time cannot precede recorded GPS data")
            session.ended_at = finished_at
            session.state = "finished"
            snapshot = session.snapshot()
        await self._publish_snapshot(session_id, snapshot)
        return snapshot

    async def export_tcx(self, session_id: str, *, require_finished: bool = True) -> bytes:
        async with self._lock:
            session = self._require(session_id)
            if require_finished and session.state != "finished":
                raise LiveSessionConflict("Finish the session before exporting it")
            if len(session.points) < 2:
                raise LiveSessionConflict("At least two accepted GPS samples are required")
            return build_tcx(session)

    async def reserve_upload(self, session_id: str | None) -> tuple[bytes | None, dict[str, Any]]:
        async with self._lock:
            session = self._require(session_id)
            if session.strava_upload is not None:
                return None, dict(session.strava_upload)
            if session.upload_in_progress:
                raise LiveSessionConflict("A Strava upload is already in progress")
            if session.state != "finished":
                raise LiveSessionConflict("Finish the session before uploading it to Strava")
            if len(session.points) < 2:
                raise LiveSessionConflict("At least two accepted GPS samples are required")
            session.upload_in_progress = True
            return build_tcx(session), {
                "session_id": session.id,
                "name": session.name,
                "sport_type": session.sport_type,
            }

    async def complete_upload(self, session_id: str | None, upload: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            session = self._require(session_id)
            session.upload_in_progress = False
            session.strava_upload = dict(upload)
            snapshot = session.snapshot()
        await self._publish_snapshot(session_id, snapshot)
        return snapshot

    async def abort_upload(self, session_id: str | None) -> None:
        async with self._lock:
            try:
                session = self._require(session_id)
            except LiveSessionNotFound:
                session = None
            if session is not None:
                session.upload_in_progress = False

    async def update_upload(self, session_id: str, upload: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            session = self._require(session_id)
            session.strava_upload = dict(upload)
            snapshot = session.snapshot()
        await self._publish_snapshot(session_id, snapshot)
        return snapshot

    async def subscribe(self, session_id: str) -> asyncio.Queue:
        async with self._lock:
            self._require(session_id)
            queue: asyncio.Queue = asyncio.Queue(maxsize=10)
            self._subscribers.setdefault(session_id, set()).add(queue)
            return queue

    async def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(session_id)
            if subscribers:
                subscribers.discard(queue)
                if not subscribers:
                    self._subscribers.pop(session_id, None)

    async def _publish(self, session: LiveSession) -> None:
        await self._publish_snapshot(session.id, session.snapshot())

    async def _publish_snapshot(self, session_id: str, snapshot: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(session_id, set())):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(snapshot)


TCX_NS = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
ACTIVITY_EXT_NS = "http://www.garmin.com/xmlschemas/ActivityExtension/v2"
ET.register_namespace("", TCX_NS)
ET.register_namespace("xsi", XSI_NS)
ET.register_namespace("ae", ACTIVITY_EXT_NS)


def _element(parent: ET.Element, name: str, text: Any | None = None, *, ns: str = TCX_NS) -> ET.Element:
    child = ET.SubElement(parent, f"{{{ns}}}{name}")
    if text is not None:
        child.text = str(text)
    return child


def build_tcx(session: LiveSession) -> bytes:
    root = ET.Element(f"{{{TCX_NS}}}TrainingCenterDatabase")
    activities = _element(root, "Activities")
    activity = _element(activities, "Activity")
    activity.set("Sport", "Running")
    _element(activity, "Id", iso(session.started_at))
    lap = _element(activity, "Lap")
    lap.set("StartTime", iso(session.started_at) or "")
    _element(lap, "TotalTimeSeconds", f"{session.active_elapsed_seconds():.3f}")
    _element(lap, "DistanceMeters", f"{session.points[-1].distance_m:.3f}")
    _element(lap, "Calories", "0")
    _element(lap, "Intensity", "Active")
    _element(lap, "TriggerMethod", "Manual")

    tracks: dict[int, ET.Element] = {}
    for point in session.points:
        track = tracks.get(point.track_index)
        if track is None:
            track = _element(lap, "Track")
            tracks[point.track_index] = track
        trackpoint = _element(track, "Trackpoint")
        _element(trackpoint, "Time", iso(point.timestamp))
        position = _element(trackpoint, "Position")
        _element(position, "LatitudeDegrees", f"{point.latitude:.8f}")
        _element(position, "LongitudeDegrees", f"{point.longitude:.8f}")
        if point.altitude_m is not None:
            _element(trackpoint, "AltitudeMeters", f"{point.altitude_m:.3f}")
        _element(trackpoint, "DistanceMeters", f"{point.distance_m:.3f}")
        if point.heart_rate_bpm is not None:
            heart_rate = _element(trackpoint, "HeartRateBpm")
            _element(heart_rate, "Value", point.heart_rate_bpm)
        if point.cadence_spm is not None or point.speed_mps is not None:
            extensions = _element(trackpoint, "Extensions")
            tpx = _element(extensions, "TPX", ns=ACTIVITY_EXT_NS)
            if point.speed_mps is not None:
                _element(tpx, "Speed", f"{point.speed_mps:.4f}", ns=ACTIVITY_EXT_NS)
            if point.cadence_spm is not None:
                _element(tpx, "RunCadence", point.cadence_spm, ns=ACTIVITY_EXT_NS)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
