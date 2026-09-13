"""Server-side perception pipeline: Capture, Detect, Localize, Estimate, Track, Triage, Speak.

This is the plan's Appendix A.1 loop (§6's seven stages) written against video
files and frame iterators rather than a live camera, which is the path the plan
itself sanctions for "the laptop demo and eval replays". There is no camera and
no audio device in this environment, so this module is the wiring, not a result:

* It has never been run against real footage here. ``ultralytics`` and
  ``opencv-python-headless`` are an optional extra (``pip install '.[perception]'``)
  and are not installed.
* The ``stage_latency_ms`` on each yielded event measures our own frame loop on
  whatever machine runs it. It excludes camera capture and audio playback, so it
  is **not** the plan's <400 ms end-to-end budget and must never be reported as
  one. The budget itself travels on the event as ``max_latency_ms`` - a target to
  compare against, not a measurement.
* Detection recall, zone accuracy and false-alert rate are unmeasured. Only the
  triage logic in ``triage.py`` is tested (see ``perception_eval.py``).

The heavy dependencies are imported lazily inside the functions that need them,
so importing this module - and therefore the FastAPI app - works without torch
installed, and asking for the pipeline without it fails with an actionable
message instead of an ImportError traceback from three libraries down.
"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable, Iterator

from .observability import record_alert_event
from .triage import AlertEvent, Detection, Triage

DEFAULT_MODEL = "yolo11n.pt"
DEFAULT_TRACKER = "bytetrack.yaml"
DEFAULT_CONFIDENCE = 0.45
DEFAULT_IMAGE_SIZE = 640
INSTALL_HINT = "pip install '.[perception]'"


class PerceptionDependencyError(ImportError):
    """Raised when the optional perception extra is not installed."""


def _require(module: str, package: str):
    """Import an optional perception dependency or explain how to get it."""
    try:
        return __import__(module)
    except ImportError as exc:  # includes the sys.modules-shadowed case
        raise PerceptionDependencyError(
            f"{module} is required for the perception pipeline but is not installed. "
            f"Install the optional extra: {INSTALL_HINT} (provides {package}). "
            "Triage logic in runsense.triage needs none of this and stays importable."
        ) from exc


def load_cv2():
    """The Capture stage's dependency."""
    return _require("cv2", "opencv-python-headless")


def load_yolo(model_path: str = DEFAULT_MODEL):
    """The Detect and Track stages: YOLO11n with Ultralytics' built-in ByteTrack."""
    _require("ultralytics", "ultralytics")
    from ultralytics import YOLO  # noqa: PLC0415 - lazy on purpose

    return YOLO(model_path)


def iter_video_frames(path: str | Path) -> Iterator[Any]:
    """Stage 1, Capture: yield decoded frames from a video file.

    A file, not a camera: no capture device exists here, and eval replays are
    what this path is for.
    """
    cv2 = load_cv2()
    resolved = str(path)
    if not Path(resolved).exists():
        raise FileNotFoundError(f"No video at {resolved}")
    capture = cv2.VideoCapture(resolved)
    if not capture.isOpened():
        raise ValueError(f"OpenCV could not open {resolved}")
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                return
            yield frame
    finally:
        capture.release()


def frames_from(source: str | Path | Iterable[Any]) -> Iterator[Any]:
    """Accept either a video path or an already-decoded frame iterable."""
    if isinstance(source, (str, Path)):
        return iter_video_frames(source)
    return iter(source)


def detections_from_result(result: Any, names: Any, frame_index: int, frame_width: float,
                           frame_height: float) -> tuple[list[Detection], int]:
    """Stages 2-5: convert one Ultralytics result into Detections.

    Returns the detections plus the count of boxes dropped for having no track
    id. Debounce and hysteresis are per-track, so an untracked box cannot be
    de-duplicated; folding them all onto a shared sentinel id (as the plan's
    sketch does) would blend distinct objects into one phantom track and
    announce the wrong thing. Dropping and counting them is the honest option.
    """
    detections: list[Detection] = []
    untracked = 0
    for box in getattr(result, "boxes", None) or []:
        track_id = getattr(box, "id", None)
        if track_id is None:
            untracked += 1
            continue
        x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
        class_index = int(box.cls[0]) if hasattr(box.cls, "__getitem__") else int(box.cls)
        obj_class = str(names[class_index]) if names is not None else str(class_index)
        confidence = float(box.conf[0]) if getattr(box, "conf", None) is not None else 1.0
        detections.append(Detection(frame_index=frame_index, track_id=int(track_id.item())
                                    if hasattr(track_id, "item") else int(track_id),
                                    obj_class=obj_class, x1=x1, y1=y1, x2=x2, y2=y2,
                                    frame_width=frame_width, frame_height=frame_height,
                                    confidence=confidence))
    return detections, untracked


def default_speaker(event: AlertEvent) -> str:
    """Stage 7, Speak: hand the utterance to the Phase 3 delivery path.

    Returns the clip id, or one of delivery's honest markers when ElevenLabs is
    not configured. It never raises: a missing optional voice must not stop the
    alert stream, and the marker is recorded on the event so nobody can mistake
    an unsynthesized cue for a spoken one.
    """
    from .delivery import blocking, speak  # noqa: PLC0415 - avoids an import cycle at module load

    return blocking(speak(event.utterance))


def run_pipeline(source: str | Path | Iterable[Any], model_path: str = DEFAULT_MODEL,
                 conf: float = DEFAULT_CONFIDENCE, imgsz: int = DEFAULT_IMAGE_SIZE,
                 tracker: str = DEFAULT_TRACKER, classes: list[int] | None = None,
                 speaker: Callable[[AlertEvent], Any] | None = default_speaker,
                 triage: Triage | None = None, max_frames: int | None = None,
                 model: Any | None = None, session_id: str | None = None,
                 record_alerts: bool = True, db_path: str | None = None) -> Iterator[dict]:
    """Run the seven-stage loop over a video file or frame iterable.

    Yields one dict per spoken alert: the triage event plus ``stage_latency_ms``
    (this loop's own frame time, not an end-to-end capture-to-audio figure) and
    the speak channel's result. Frames with no alert yield nothing.

    ``model`` lets a caller inject an already-loaded detector; ``speaker=None``
    runs the pipeline mute, which is what an eval replay wants.

    Each yielded alert is also mirrored into the typed ``alerts`` table so a run's
    hazards are queryable afterwards; ``record_alerts=False`` turns that off and
    ``db_path`` redirects it (default: ``RUNSENSE_DB``). The write is best effort -
    a failed record adds ``"recorded": False`` to the event and never interrupts
    the alert stream, because a database problem must not silence a hazard cue.
    """
    detector = model if model is not None else load_yolo(model_path)
    triage = triage or Triage()
    for frame_index, frame in enumerate(frames_from(source)):
        if max_frames is not None and frame_index >= max_frames:
            return
        started = perf_counter()
        height, width = frame.shape[:2]
        results = detector.track(frame, persist=True, conf=conf, imgsz=imgsz, tracker=tracker,
                                 classes=classes, verbose=False)
        detections, untracked = detections_from_result(results[0], getattr(detector, "names", None),
                                                       frame_index, float(width), float(height))
        triage.observe_all(detections)
        for event in triage.emit(frame_index):
            payload = event.to_dict()
            payload["stage_latency_ms"] = round((perf_counter() - started) * 1000, 3)
            payload["latency_scope"] = "decode_to_dispatch"  # excludes capture and playback
            payload["untracked_boxes"] = untracked
            payload["speak_result"] = speaker(event) if speaker is not None else None
            payload["recorded"] = record_alert_event(payload, session_id, path=db_path) if record_alerts else False
            yield payload


__all__ = [
    "DEFAULT_CONFIDENCE",
    "DEFAULT_IMAGE_SIZE",
    "DEFAULT_MODEL",
    "DEFAULT_TRACKER",
    "INSTALL_HINT",
    "PerceptionDependencyError",
    "default_speaker",
    "detections_from_result",
    "frames_from",
    "iter_video_frames",
    "load_cv2",
    "load_yolo",
    "run_pipeline",
]
