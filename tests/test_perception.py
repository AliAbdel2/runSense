"""The YOLO/ByteTrack wiring: import-time safety and result conversion.

``ultralytics`` and ``opencv-python-headless`` are an optional extra and are not
installed here, so these tests cover the contract the base app depends on - the
module imports, and asking for the pipeline without the extra fails with an
actionable message - plus the pure conversion step, driven by a stub result
object rather than a real model. No inference runs; nothing here is evidence
about detection quality.
"""

import sys

import pytest

from runsense import db, perception
from runsense.perception import (
    INSTALL_HINT,
    PerceptionDependencyError,
    detections_from_result,
    frames_from,
    run_pipeline,
)
from runsense.triage import Triage


@pytest.fixture(autouse=True)
def typed_db_in_tmp(tmp_path, monkeypatch):
    """Keep every alert these tests record inside the test's own database file."""
    monkeypatch.setenv("RUNSENSE_DB", str(tmp_path / "typed.sqlite3"))


class _Value(list):
    """Stands in for a torch tensor: indexable, with .tolist() and .item()."""

    def tolist(self):
        return list(self)

    def item(self):
        return self[0]


class _Box:
    def __init__(self, xyxy, cls, track_id, conf=0.9):
        self.xyxy = [_Value(xyxy)]
        self.cls = _Value([cls])
        self.conf = _Value([conf])
        self.id = None if track_id is None else _Value([track_id])


class _Result:
    def __init__(self, boxes):
        self.boxes = boxes


class _Frame:
    """The only attribute the loop uses from a decoded frame."""

    shape = (384, 640, 3)


class _Model:
    """A detector stub: returns scripted results, one per frame."""

    names = {0: "person", 2: "car"}

    def __init__(self, per_frame):
        self.per_frame = per_frame
        self.calls = []

    def track(self, frame, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        return [_Result(self.per_frame[index] if index < len(self.per_frame) else [])]


def test_module_imports_without_the_optional_extra():
    assert "ultralytics" not in sys.modules and "cv2" not in sys.modules


@pytest.mark.parametrize("loader,module", [("load_yolo", "ultralytics"), ("load_cv2", "cv2")])
def test_missing_dependency_raises_an_actionable_error(loader, module, monkeypatch):
    monkeypatch.setitem(sys.modules, module, None)  # simulates "not installed"
    with pytest.raises(PerceptionDependencyError) as raised:
        getattr(perception, loader)()
    message = str(raised.value)
    assert module in message and INSTALL_HINT in message
    assert isinstance(raised.value, ImportError)


def test_pipeline_refuses_to_start_without_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "ultralytics", None)
    with pytest.raises(PerceptionDependencyError):
        next(run_pipeline(iter([_Frame()])))


def test_video_capture_requires_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", None)
    with pytest.raises(PerceptionDependencyError):
        next(frames_from("clips/does-not-exist.mp4"))


def test_frames_from_passes_an_iterable_straight_through():
    frames = [_Frame(), _Frame()]
    assert list(frames_from(frames)) == frames


def test_detections_from_result_maps_boxes_and_class_names():
    result = _Result([_Box([100, 50, 200, 300], 0, 7)])
    detections, untracked = detections_from_result(result, _Model.names, 4, 640.0, 384.0)
    assert untracked == 0
    detection = detections[0]
    assert (detection.track_id, detection.obj_class, detection.frame_index) == (7, "person", 4)
    assert (detection.x1, detection.y2) == (100.0, 300.0)
    assert detection.height_ratio == pytest.approx(250 / 384)


def test_untracked_boxes_are_dropped_and_counted():
    result = _Result([_Box([0, 0, 10, 10], 0, None), _Box([0, 0, 10, 10], 2, 3)])
    detections, untracked = detections_from_result(result, _Model.names, 0, 640.0, 384.0)
    assert untracked == 1
    assert [d.obj_class for d in detections] == ["car"]


def test_empty_result_yields_no_detections():
    detections, untracked = detections_from_result(_Result([]), _Model.names, 0, 640.0, 384.0)
    assert (detections, untracked) == ([], 0)


def test_pipeline_yields_triaged_alerts_and_calls_the_speaker():
    # A centred, near person held across four frames: one DANGER after debounce.
    near_person = [_Box([250, 20, 390, 360], 0, 1)]
    model = _Model([near_person] * 4)
    said = []
    events = list(run_pipeline([_Frame()] * 4, model=model, speaker=lambda event: said.append(
        event.utterance) or "clip-123", triage=Triage()))
    assert [event["tier"] for event in events] == ["danger"]
    assert said == ["Stop - person ahead"]
    assert events[0]["speak_result"] == "clip-123"
    assert events[0]["frame_index"] == 2 and events[0]["untracked_boxes"] == 0
    # The recorded timing is this loop's own, explicitly not capture-to-audio.
    assert events[0]["latency_scope"] == "decode_to_dispatch"
    assert events[0]["stage_latency_ms"] >= 0
    assert events[0]["max_latency_ms"] == 400  # the plan's budget, carried, not measured


def test_pipeline_can_run_mute():
    model = _Model([[_Box([250, 20, 390, 360], 0, 1)]] * 4)
    events = list(run_pipeline([_Frame()] * 4, model=model, speaker=None))
    assert [event["speak_result"] for event in events] == [None]


def test_pipeline_passes_tracking_options_to_the_model():
    model = _Model([[]])
    list(run_pipeline([_Frame()], model=model, speaker=None, conf=0.3, imgsz=416, classes=[0]))
    assert model.calls[0]["persist"] is True
    assert (model.calls[0]["conf"], model.calls[0]["imgsz"], model.calls[0]["classes"]) == (
        0.3, 416, [0])
    assert model.calls[0]["tracker"] == "bytetrack.yaml"


def test_max_frames_stops_the_loop():
    model = _Model([[_Box([250, 20, 390, 360], 0, 1)]] * 10)
    assert list(run_pipeline([_Frame()] * 10, model=model, speaker=None, max_frames=2)) == []
    assert len(model.calls) == 2


def test_alerts_are_mirrored_into_the_typed_table(tmp_path):
    path = str(tmp_path / "typed.sqlite3")
    model = _Model([[_Box([250, 20, 390, 360], 0, 1)]] * 4)
    events = list(run_pipeline([_Frame()] * 4, model=model, speaker=None, session_id="sess-1",
                               db_path=path))
    assert [event["recorded"] for event in events] == [True]

    stored = db.TypedStore(path).list_alerts("sess-1")
    assert len(stored) == 1
    assert (stored[0].obj_class, stored[0].zone, stored[0].tier) == ("person", "center", "danger")
    # The triage event's `distance` bucket is what the distance_bucket column holds.
    assert stored[0].distance_bucket == events[0]["distance"]
    assert stored[0].spoken is events[0]["spoken"]
    assert stored[0].latency_ms == pytest.approx(events[0]["stage_latency_ms"])


def test_alert_recording_can_be_turned_off(tmp_path):
    path = str(tmp_path / "typed.sqlite3")
    model = _Model([[_Box([250, 20, 390, 360], 0, 1)]] * 4)
    events = list(run_pipeline([_Frame()] * 4, model=model, speaker=None, record_alerts=False,
                               db_path=path))
    assert [event["recorded"] for event in events] == [False]
    assert db.TypedStore(path).list_alerts() == []


def test_a_failing_typed_store_never_silences_an_alert(tmp_path, monkeypatch):
    """The non-fatal guarantee: a broken database must not stop a hazard cue."""

    def exploding(self, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(db.TypedStore, "record_alert", exploding)
    said = []
    model = _Model([[_Box([250, 20, 390, 360], 0, 1)]] * 4)
    events = list(run_pipeline([_Frame()] * 4, model=model, session_id="sess-1",
                               speaker=lambda event: said.append(event.utterance) or "clip-1",
                               db_path=str(tmp_path / "typed.sqlite3")))
    # The alert is still triaged, still spoken, still yielded - only flagged unrecorded.
    assert [event["tier"] for event in events] == ["danger"]
    assert said == ["Stop - person ahead"]
    assert events[0]["speak_result"] == "clip-1"
    assert events[0]["recorded"] is False


def test_default_speaker_is_wired_to_the_delivery_path(monkeypatch):
    spoken = []

    async def fake_speak(text):
        spoken.append(text)
        return "tts_not_configured"

    monkeypatch.setattr("runsense.delivery.speak", fake_speak)
    model = _Model([[_Box([250, 20, 390, 360], 0, 1)]] * 4)
    events = list(run_pipeline([_Frame()] * 4, model=model))
    assert spoken == ["Stop - person ahead"]
    assert events[0]["speak_result"] == "tts_not_configured"
