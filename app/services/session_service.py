"""Concurrency-safe live run service with aggregate persistence and TCX export."""
from __future__ import annotations

import asyncio
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree as ET


def utc(value):
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def haversine(a, b, c, d):
    radius = 6_371_000.0
    p1, p2, dp, dl = math.radians(a), math.radians(c), math.radians(c - a), math.radians(d - b)
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def pace_text(seconds):
    if seconds is None: return None
    minutes, remainder = divmod(max(0, round(seconds)), 60)
    return f"{minutes} {'minute' if minutes == 1 else 'minutes'}" + (f" {remainder} {'second' if remainder == 1 else 'seconds'}" if remainder else "") + " per kilometre"


class LiveSessionError(RuntimeError): pass
class LiveSessionNotFound(LiveSessionError): pass
class LiveSessionConflict(LiveSessionError): pass


@dataclass
class Point:
    timestamp: datetime; latitude: float; longitude: float; accuracy_m: float; altitude_m: float | None; heart_rate_bpm: int | None; cadence_spm: int | None; distance_m: float; speed_mps: float | None; track_index: int


@dataclass
class LiveSession:
    id: str; name: str; sport_type: str; started_at: datetime; state: str = "active"; ended_at: datetime | None = None; paused_at: datetime | None = None; paused_seconds: float = 0; track_index: int = 0; points: list[Point] = field(default_factory=list); rejected_samples: int = 0; strava_upload: dict | None = None; upload_in_progress: bool = False; track_started_at: datetime | None = None
    def __post_init__(self): self.track_started_at = self.track_started_at or self.started_at
    def elapsed(self, as_of=None):
        end = self.ended_at or as_of or (self.points[-1].timestamp if self.points else datetime.now(timezone.utc)); end = max(utc(end), self.started_at); paused = self.paused_seconds + ((end - self.paused_at).total_seconds() if self.paused_at else 0); return max(0, (end - self.started_at).total_seconds() - paused)
    def pace(self):
        if self.state != "active" or len(self.points) < 2: return None
        latest = self.points[-1]; points = [p for p in self.points if p.track_index == latest.track_index and (latest.timestamp - p.timestamp).total_seconds() <= 10]
        if len(points) < 2: return None
        seconds, distance = (points[-1].timestamp - points[0].timestamp).total_seconds(), points[-1].distance_m - points[0].distance_m
        return seconds * 1000 / distance if seconds > 0 and distance >= 5 else None
    def snapshot(self):
        distance = self.points[-1].distance_m if self.points else 0; current = self.pace(); elapsed = self.elapsed(self.ended_at or (self.points[-1].timestamp if self.points else None)); latest = self.points[-1] if self.points else None
        average = elapsed * 1000 / distance if distance >= 5 else None
        return {"session_id": self.id, "name": self.name, "sport_type": self.sport_type, "state": self.state, "started_at": iso(self.started_at), "ended_at": iso(self.ended_at), "distance_m": round(distance, 2), "active_elapsed_seconds": round(elapsed, 3), "current_pace_seconds_per_km": round(current, 1) if current else None, "current_pace_spoken": pace_text(current), "average_pace_seconds_per_km": round(average, 1) if average else None, "average_pace_spoken": pace_text(average), "heart_rate_bpm": latest.heart_rate_bpm if latest else None, "cadence_spm": latest.cadence_spm if latest else None, "spoken_status": f"Current pace is {pace_text(current)}. Distance is {round(distance)} metres." if current else f"Distance is {round(distance)} metres.", "accepted_samples": len(self.points), "rejected_samples": self.rejected_samples, "strava_upload": self.strava_upload}


class LiveSessionManager:
    def __init__(self, persist=None): self._sessions = {}; self._lock = asyncio.Lock(); self._subscribers = {}; self.persist = persist
    def _save(self, session):
        if self.persist: self.persist(session.snapshot())
    def _require(self, session_id):
        session = next(reversed(self._sessions.values()), None) if session_id is None else self._sessions.get(session_id)
        if not session: raise LiveSessionNotFound("Live session not found")
        return session
    async def start(self, *, name, sport_type, started_at=None):
        session = LiveSession(str(uuid.uuid4()), name.strip(), sport_type, utc(started_at or datetime.now(timezone.utc)))
        async with self._lock: self._sessions[session.id] = session; self._save(session)
        await self._publish(session); return session.snapshot()
    async def get(self, session_id=None):
        async with self._lock: return self._require(session_id).snapshot()
    def _sample(self, session, row):
        if len(session.points) >= 100_000: raise LiveSessionConflict("Session sample limit reached")
        timestamp, accuracy = utc(row["timestamp"]), float(row["accuracy_m"])
        if timestamp < session.track_started_at: session.rejected_samples += 1; return {"accepted": False, "reason": "sample_before_active_segment"}
        if accuracy > 50: session.rejected_samples += 1; return {"accepted": False, "reason": "gps_accuracy_too_low"}
        previous, distance, speed = session.points[-1] if session.points else None, 0, None
        if previous:
            distance = previous.distance_m
            if previous.track_index == session.track_index:
                seconds = (timestamp - previous.timestamp).total_seconds()
                if seconds <= 0: session.rejected_samples += 1; return {"accepted": False, "reason": "timestamp_not_increasing"}
                segment = haversine(previous.latitude, previous.longitude, float(row["latitude"]), float(row["longitude"])); speed = segment / seconds
                if speed > 12.5: session.rejected_samples += 1; return {"accepted": False, "reason": "implausible_running_speed"}
                if segment >= 1.5: distance += segment
        session.points.append(Point(timestamp, float(row["latitude"]), float(row["longitude"]), accuracy, row.get("altitude_m"), row.get("heart_rate_bpm"), row.get("cadence_spm"), distance, speed, session.track_index))
        return {"accepted": True, "timestamp": iso(timestamp), "distance_m": round(distance, 2)}
    async def add_samples(self, session_id, rows):
        async with self._lock:
            session = self._require(session_id)
            if session.state != "active": raise LiveSessionConflict("GPS samples are accepted only while the session is active")
            result = [self._sample(session, row) for row in rows]; self._save(session); snapshot = session.snapshot()
        await self._publish_snapshot(session_id, snapshot); return {"samples": result, "live": snapshot}
    async def pause(self, session_id, at=None):
        async with self._lock:
            session = self._require(session_id)
            if session.state != "active": raise LiveSessionConflict("Only an active session can be paused")
            value = utc(at or datetime.now(timezone.utc))
            if value < session.started_at or (session.points and value < session.points[-1].timestamp): raise LiveSessionConflict("Pause time cannot precede recorded session data")
            session.paused_at, session.state = value, "paused"; self._save(session); snapshot = session.snapshot()
        await self._publish_snapshot(session_id, snapshot); return snapshot
    async def resume(self, session_id, at=None):
        async with self._lock:
            session = self._require(session_id)
            if session.state != "paused" or not session.paused_at: raise LiveSessionConflict("Only a paused session can be resumed")
            value = utc(at or datetime.now(timezone.utc))
            if value < session.paused_at: raise LiveSessionConflict("Resume time cannot precede pause time")
            session.paused_seconds += (value - session.paused_at).total_seconds(); session.paused_at = None; session.track_index += 1; session.track_started_at = value; session.state = "active"; self._save(session); snapshot = session.snapshot()
        await self._publish_snapshot(session_id, snapshot); return snapshot
    async def finish(self, session_id=None, at=None):
        async with self._lock:
            session = self._require(session_id)
            if session.state == "finished": return session.snapshot()
            value = utc(at or datetime.now(timezone.utc))
            if session.paused_at: session.paused_seconds += max(0, (value - session.paused_at).total_seconds()); session.paused_at = None
            if value < session.started_at or (session.points and value < session.points[-1].timestamp): raise LiveSessionConflict("Finish time cannot precede recorded session data")
            session.ended_at, session.state = value, "finished"; self._save(session); snapshot = session.snapshot()
        await self._publish_snapshot(session_id, snapshot); return snapshot
    async def export_tcx(self, session_id):
        async with self._lock:
            session = self._require(session_id)
            if session.state != "finished": raise LiveSessionConflict("Finish the session before exporting it")
            if len(session.points) < 2: raise LiveSessionConflict("At least two accepted GPS samples are required")
            return build_tcx(session)
    async def reserve_upload(self, session_id):
        async with self._lock:
            session = self._require(session_id)
            if session.strava_upload: return None, dict(session.strava_upload)
            if session.upload_in_progress: raise LiveSessionConflict("A Strava upload is already in progress")
            if session.state != "finished" or len(session.points) < 2: raise LiveSessionConflict("Finish the session before uploading it to Strava")
            session.upload_in_progress = True; return build_tcx(session), {"session_id": session.id, "name": session.name, "sport_type": session.sport_type}
    async def complete_upload(self, session_id, upload):
        async with self._lock: session = self._require(session_id); session.upload_in_progress = False; session.strava_upload = dict(upload); self._save(session); snapshot = session.snapshot()
        await self._publish_snapshot(session_id, snapshot); return snapshot
    async def abort_upload(self, session_id):
        async with self._lock:
            if session_id in self._sessions: self._sessions[session_id].upload_in_progress = False
    async def update_upload(self, session_id, upload): return await self.complete_upload(session_id, upload)
    async def subscribe(self, session_id):
        async with self._lock: self._require(session_id); queue = asyncio.Queue(maxsize=10); self._subscribers.setdefault(session_id, set()).add(queue); return queue
    async def unsubscribe(self, session_id, queue):
        async with self._lock: self._subscribers.get(session_id, set()).discard(queue)
    async def _publish(self, session): await self._publish_snapshot(session.id, session.snapshot())
    async def _publish_snapshot(self, session_id, snapshot):
        for queue in list(self._subscribers.get(session_id, set())):
            if queue.full(): queue.get_nowait()
            queue.put_nowait(snapshot)


TCX = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"; EXT = "http://www.garmin.com/xmlschemas/ActivityExtension/v2"; ET.register_namespace("", TCX); ET.register_namespace("ae", EXT)
def _element(parent, name, value=None, ns=TCX):
    child = ET.SubElement(parent, f"{{{ns}}}{name}"); child.text = str(value) if value is not None else None; return child
def build_tcx(session):
    root = ET.Element(f"{{{TCX}}}TrainingCenterDatabase"); activity = _element(_element(root, "Activities"), "Activity"); activity.set("Sport", "Running"); _element(activity, "Id", iso(session.started_at)); lap = _element(activity, "Lap"); lap.set("StartTime", iso(session.started_at)); _element(lap, "TotalTimeSeconds", f"{session.elapsed():.3f}"); _element(lap, "DistanceMeters", f"{session.points[-1].distance_m:.3f}"); _element(lap, "Calories", 0); _element(lap, "Intensity", "Active"); _element(lap, "TriggerMethod", "Manual")
    tracks = {}
    for point in session.points:
        track = tracks.setdefault(point.track_index, _element(lap, "Track")); node = _element(track, "Trackpoint"); _element(node, "Time", iso(point.timestamp)); position = _element(node, "Position"); _element(position, "LatitudeDegrees", f"{point.latitude:.8f}"); _element(position, "LongitudeDegrees", f"{point.longitude:.8f}");
        if point.altitude_m is not None: _element(node, "AltitudeMeters", f"{point.altitude_m:.3f}")
        _element(node, "DistanceMeters", f"{point.distance_m:.3f}")
        if point.heart_rate_bpm is not None: _element(_element(node, "HeartRateBpm"), "Value", point.heart_rate_bpm)
        if point.cadence_spm is not None or point.speed_mps is not None:
            extension = _element(_element(node, "Extensions"), "TPX", ns=EXT)
            if point.speed_mps is not None: _element(extension, "Speed", f"{point.speed_mps:.4f}", ns=EXT)
            if point.cadence_spm is not None: _element(extension, "RunCadence", point.cadence_spm, ns=EXT)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
