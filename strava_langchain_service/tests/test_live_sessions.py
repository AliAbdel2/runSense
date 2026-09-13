import asyncio
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import pytest

from app.live_sessions import LiveSessionManager


def run(coro):
    return asyncio.run(coro)


def point(at, longitude, **extra):
    return {
        "timestamp": at,
        "latitude": 0.0,
        "longitude": longitude,
        "accuracy_m": extra.get("accuracy_m", 5.0),
        "altitude_m": 20.0,
        "heart_rate_bpm": extra.get("heart_rate_bpm"),
        "cadence_spm": extra.get("cadence_spm"),
    }


def test_live_distance_pace_pause_and_tcx_export():
    async def scenario():
        manager = LiveSessionManager()
        start = datetime(2026, 9, 13, 8, tzinfo=timezone.utc)
        session = await manager.start(name="Accessible Run", sport_type="Run", started_at=start)
        session_id = session["session_id"]
        first = await manager.add_samples(
            session_id,
            [
                point(start, 0.0, heart_rate_bpm=140, cadence_spm=168),
                point(start + timedelta(seconds=5), 0.0001, heart_rate_bpm=145, cadence_spm=170),
                point(start + timedelta(seconds=10), 0.0002, heart_rate_bpm=148, cadence_spm=172),
                point(start + timedelta(seconds=11), 0.0003, accuracy_m=500),
            ],
        )
        live = first["live"]
        assert live["distance_m"] == pytest.approx(22.24, abs=0.1)
        assert live["current_pace_seconds_per_km"] == pytest.approx(449.7, abs=2)
        assert live["current_pace_spoken"] == "7 minutes 30 seconds per kilometre"
        assert live["spoken_status"] == (
            "Current pace is 7 minutes 30 seconds per kilometre. Distance is 22 metres."
        )
        assert live["heart_rate_bpm"] == 148
        assert live["cadence_spm"] == 172
        assert live["rejected_samples"] == 1

        await manager.pause(session_id, start + timedelta(seconds=11))
        await manager.resume(session_id, start + timedelta(seconds=21))
        resumed = await manager.add_samples(
            session_id,
            [
                point(start + timedelta(seconds=22), 0.01),
                point(start + timedelta(seconds=27), 0.0101),
            ],
        )
        # Resuming starts a new TCX track, so the off-session location jump is not counted.
        assert resumed["live"]["distance_m"] == pytest.approx(33.36, abs=0.2)
        final = await manager.finish(session_id, start + timedelta(seconds=30))
        assert final["state"] == "finished"
        assert final["active_elapsed_seconds"] == 20

        tcx = await manager.export_tcx(session_id)
        root = ET.fromstring(tcx)
        namespace = {"tcx": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}
        extensions = {"ae": "http://www.garmin.com/xmlschemas/ActivityExtension/v2"}
        assert len(root.findall(".//tcx:Track", namespace)) == 2
        assert len(root.findall(".//tcx:Trackpoint", namespace)) == 5
        assert root.findtext(".//tcx:DistanceMeters", namespaces=namespace) == "33.358"
        assert root.findtext(".//tcx:HeartRateBpm/tcx:Value", namespaces=namespace) == "140"
        assert root.findtext(".//ae:RunCadence", namespaces=extensions) == "168"

    run(scenario())
