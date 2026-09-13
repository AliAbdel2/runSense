"""Pure obstacle-alert triage: zone/distance bucketing, debounce, tiers, pre-emption.

This module deliberately imports nothing heavier than the standard library. The
YOLO/ByteTrack half of the pipeline lives in ``perception.py`` behind lazy
imports; everything decision-shaped lives here so it can be unit-tested exactly,
on hand-built :class:`Detection` objects, with no model, no camera and no torch.

What this module is evidence of, and what it is not
---------------------------------------------------
The rules below are a faithful, deterministic implementation of the plan's
trigger table (§6): they can be, and are, tested. They say nothing about whether
a real camera and a real detector would produce the right :class:`Detection`
stream in the first place. Detection recall, zone accuracy against ground truth,
false-alert rate and end-to-end capture-to-audio latency are unmeasured; see
``perception_eval.py`` for the wording used in the evaluation report.

Type choice: :class:`Detection` is a frozen ``@dataclass`` rather than one of
``models.py``'s Pydantic ``StrictModel``s. Those model request/response payloads
crossing a trust boundary, where per-field validation earns its cost. A
Detection is an internal, per-frame, per-object value produced by our own
converter at (target) 30 frames per second with tens of objects per frame;
``slots=True`` keeps it cheap, and the only invariant that actually matters
(positive frame dimensions) is checked in ``__post_init__``.

Thresholds (0.45/0.20 distance proxy, thirds for zones, 3-frame debounce,
15-frame clear) come from the plan. The "approaching" thresholds do not — the
plan is qualitative there — so they are named constants with a documented
rationale below, and they are untuned against real footage.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from typing import Iterable, Literal

Zone = Literal["left", "center", "right"]
DistanceBucket = Literal["near", "mid", "far"]
Tier = Literal["danger", "warning", "notice", "silent"]

# --- plan-specified constants (RunSense_Hackathon_Plan.pdf, Figure 3 and §6) ---
NEAR_RATIO = 0.45          # bbox height / frame height above this reads as NEAR
FAR_RATIO = 0.20           # below this reads as FAR; between the two is MID
LEFT_EDGE = 1 / 3          # bbox centre-x / frame width below this is LEFT
RIGHT_EDGE = 2 / 3         # above this is RIGHT; between the two is CENTER
PERSIST_FRAMES = 3         # an object must persist this many frames to be announced
CLEAR_FRAMES = 15          # it must then be absent this many frames to be re-announced

# Per-tier speech budgets from the plan's table. They are carried on the event so
# a consumer can compare them against a measurement; nothing here measures one.
MAX_LATENCY_MS: dict[str, int] = {"danger": 400, "warning": 600, "notice": 1500}

# --- "approaching" (our operationalization; the plan only says "bbox height
# growing frame over frame" / "approaching fast") -------------------------------
# A track is approaching when its distance proxy (bbox height / frame height) has
# grown by APPROACH_GROWTH over a APPROACH_WINDOW_FRAMES-frame window, and is
# approaching *fast* at FAST_GROWTH. Growth is normalized per frame and then
# re-expanded over the window, so a dropped frame neither hides nor fakes an
# approach. The window matches the 3-frame debounce, so a track becomes eligible
# to speak and eligible to be promoted at the same moment.
#
# The two numbers are engineering placeholders, not measurements: +5% is chosen
# to sit above plausible bounding-box jitter while still firing well before an
# object crosses a bucket boundary, and +15% marks the closing speed that would
# cross a bucket in roughly one debounce window. Neither has been validated
# against real video, because no labelled footage exists in this environment.
APPROACH_WINDOW_FRAMES = 3
APPROACH_GROWTH = 1.05
FAST_GROWTH = 1.15


@dataclass(frozen=True, slots=True)
class Detection:
    """One detected object in one frame, in pixel coordinates."""

    frame_index: int
    track_id: int
    obj_class: str
    x1: float
    y1: float
    x2: float
    y2: float
    frame_width: float
    frame_height: float
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.frame_width <= 0 or self.frame_height <= 0:
            raise ValueError("Detection needs positive frame dimensions.")

    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def box_height(self) -> float:
        return abs(self.y2 - self.y1)

    @property
    def center_x_ratio(self) -> float:
        """Horizontal position of the box centre, 0.0 (left edge) to 1.0 (right)."""
        return self.center_x / self.frame_width

    @property
    def height_ratio(self) -> float:
        """The plan's distance proxy: bbox height over frame height.

        A proxy, not depth. A short object close by and a tall one further away
        can share a ratio; the plan says so explicitly and so does this.
        """
        return self.box_height / self.frame_height


@dataclass(frozen=True, slots=True)
class AlertEvent:
    """One triage decision about one track in one frame.

    ``frame_index`` is the frame that raised the decision; ``spoken_frame`` is
    the frame it actually reached the speaker on. They differ when a NOTICE waits
    for an idle queue, and that gap is the queueing delay - a real part of any
    latency budget, so it is recorded rather than hidden.
    """

    frame_index: int
    track_id: int
    obj_class: str
    zone: Zone
    distance: DistanceBucket
    tier: Tier
    approaching: bool
    utterance: str
    earcon: str
    max_latency_ms: int | None
    spoken: bool = False
    spoken_frame: int | None = None
    preempted: bool = False

    def to_dict(self) -> dict:
        return {
            "frame_index": self.frame_index,
            "spoken_frame": self.spoken_frame,
            "track_id": self.track_id,
            "obj_class": self.obj_class,
            "zone": self.zone,
            "distance": self.distance,
            "tier": self.tier,
            "approaching": self.approaching,
            "utterance": self.utterance,
            "earcon": self.earcon,
            "max_latency_ms": self.max_latency_ms,
            "spoken": self.spoken,
            "preempted": self.preempted,
        }


def zone_for(detection: Detection) -> Zone:
    """LEFT/CENTER/RIGHT from the bbox centre-x, frame split into thirds."""
    ratio = detection.center_x_ratio
    if ratio < LEFT_EDGE:
        return "left"
    if ratio > RIGHT_EDGE:
        return "right"
    return "center"


def distance_bucket_for(detection: Detection) -> DistanceBucket:
    """NEAR/MID/FAR from the bbox-height proxy: >0.45 near, 0.20-0.45 mid, <0.20 far."""
    ratio = detection.height_ratio
    if ratio > NEAR_RATIO:
        return "near"
    if ratio < FAR_RATIO:
        return "far"
    return "mid"


def tier_for(zone: Zone, distance: DistanceBucket, approaching: bool = False,
             approaching_fast: bool = False) -> Tier:
    """The plan's trigger table, as one pure function.

    DANGER  CENTER + NEAR, or any zone NEAR and approaching fast.
    WARNING LEFT/RIGHT + NEAR, or MID and approaching (Figure 3's "approaching
            objects are promoted one tier (mid+approaching = WARNING)", which
            generalizes the table's CENTER + MID approaching row).
    NOTICE  MID, not approaching.
    silent  FAR. FAR is never promoted: the table's silent row carries no
            approaching qualifier, the height proxy is least trustworthy at
            range, and an approaching far object becomes MID within a few frames
            and is announced then.
    """
    if distance == "near":
        if zone == "center" or approaching_fast:
            return "danger"
        return "warning"
    if distance == "mid":
        return "warning" if approaching else "notice"
    return "silent"


def utterance_for(obj_class: str, zone: Zone, tier: Tier) -> str:
    """The plan's zone -> utterance mapping, with the detected class substituted."""
    name = obj_class.replace("_", " ").strip() or "object"
    direction = "ahead" if zone == "center" else zone
    if tier == "danger":
        return f"Stop - {name} {direction}"
    if tier == "warning":
        return f"{name} {direction}"
    if tier == "notice":
        return f"{name} ahead" if zone == "center" else f"{name} far {zone}"
    return ""


def earcon_for(zone: Zone, tier: Tier) -> str:
    """Non-speech cue name; the plan pans WARNING to the matching ear."""
    if tier == "danger":
        return "double_tone"
    if tier == "warning":
        return f"panned_tone_{zone}"
    if tier == "notice":
        return "soft_cue"
    return ""


@dataclass
class _TrackState:
    """Per-track debounce/hysteresis bookkeeping."""

    last_seen_frame: int
    streak: int = 1
    announced: bool = False
    logged_tier: str | None = None
    # Holds the observations preceding the current one, so the oldest entry is
    # at most APPROACH_WINDOW_FRAMES frames back.
    history: deque[tuple[int, float]] = field(
        default_factory=lambda: deque(maxlen=APPROACH_WINDOW_FRAMES))

    def growth_per_window(self, frame_index: int, ratio: float) -> float:
        """Height-proxy growth over the approach window, normalized per frame.

        Returns 1.0 (no evidence of approach) until there are two observations.
        """
        if len(self.history) < 2:
            return 1.0
        past_frame, past_ratio = self.history[0]
        elapsed = frame_index - past_frame
        if elapsed <= 0 or past_ratio <= 0:
            return 1.0
        per_frame = (ratio / past_ratio) ** (1 / elapsed)
        return per_frame ** APPROACH_WINDOW_FRAMES


class Triage:
    """Stateful alert triage over a stream of per-frame detections.

    Usage mirrors the plan's Appendix A skeleton::

        tri = Triage()
        for detection in detections_for_this_frame:
            tri.observe(detection)
        for event in tri.emit(frame_index):
            speaker.say(event)

    ``emit`` must be called once per frame, including frames with no detections
    (that is how absence, and therefore the 15-frame re-announcement window, is
    counted). Every decision - spoken, queued, pre-empted or silent - is appended
    to :attr:`log`, which is what the evaluation harness reads.
    """

    def __init__(self, persist_frames: int = PERSIST_FRAMES, clear_frames: int = CLEAR_FRAMES) -> None:
        self.persist_frames = persist_frames
        self.clear_frames = clear_frames
        self._tracks: dict[int, _TrackState] = {}
        self._pending: dict[int, Detection] = {}
        self._queue: list[AlertEvent] = []
        self._frame = -1
        self.log: list[AlertEvent] = []

    # --- input ---------------------------------------------------------
    def observe(self, detection: Detection) -> None:
        """Record one detection for the frame currently being assembled.

        A repeated track id inside one frame keeps the last detection: ByteTrack
        emits at most one box per id per frame, so this is defensive only.
        """
        self._pending[detection.track_id] = detection

    def observe_all(self, detections: Iterable[Detection]) -> None:
        for detection in detections:
            self.observe(detection)

    # --- one frame of triage -------------------------------------------
    def emit(self, frame_index: int | None = None) -> list[AlertEvent]:
        """Close the current frame and return the events to speak now."""
        frame = self._resolve_frame(frame_index)
        self._frame = frame
        detections = self._pending
        self._pending = {}

        candidates = [self._update_track(detection) for detection in detections.values()]
        self._expire_absent(frame)
        for event in candidates:
            if event is not None:
                self._enqueue(event)
        return self._drain()

    def _resolve_frame(self, frame_index: int | None) -> int:
        if frame_index is not None:
            return frame_index
        if self._pending:
            return max(d.frame_index for d in self._pending.values())
        return self._frame + 1

    def _update_track(self, detection: Detection) -> AlertEvent | None:
        """Advance one track's state and return an event if it should be raised."""
        state = self._tracks.get(detection.track_id)
        if state is None:
            state = _TrackState(last_seen_frame=detection.frame_index)
            self._tracks[detection.track_id] = state
        elif detection.frame_index > state.last_seen_frame:
            # Persistence is counted over consecutive frames: a gap means the
            # detector lost the object, and the plan's 3-frame requirement is
            # about a stable, repeated observation rather than a flickering one.
            state.streak = state.streak + 1 if detection.frame_index == state.last_seen_frame + 1 else 1
            state.last_seen_frame = detection.frame_index

        ratio = detection.height_ratio
        growth = state.growth_per_window(detection.frame_index, ratio)
        state.history.append((detection.frame_index, ratio))

        zone = zone_for(detection)
        distance = distance_bucket_for(detection)
        approaching = growth >= APPROACH_GROWTH
        tier = tier_for(zone, distance, approaching, growth >= FAST_GROWTH)

        if state.streak < self.persist_frames:
            return None  # debounce: not yet persistent enough to be announced
        if tier == "silent":
            # "Logged for eval, never spoken." Logged on change only, so a far
            # object sitting in frame does not flood the log.
            if state.logged_tier != "silent":
                state.logged_tier = "silent"
                self.log.append(self._event(detection, zone, distance, "silent", approaching))
            return None
        if state.announced or any(queued.track_id == detection.track_id for queued in self._queue):
            return None  # already spoken, or already waiting its turn
        state.logged_tier = tier
        return self._event(detection, zone, distance, tier, approaching)

    def _event(self, detection: Detection, zone: Zone, distance: DistanceBucket, tier: Tier,
               approaching: bool) -> AlertEvent:
        return AlertEvent(frame_index=detection.frame_index, track_id=detection.track_id,
                          obj_class=detection.obj_class, zone=zone, distance=distance, tier=tier,
                          approaching=approaching, utterance=utterance_for(detection.obj_class, zone, tier),
                          earcon=earcon_for(zone, tier), max_latency_ms=MAX_LATENCY_MS.get(tier))

    def _expire_absent(self, frame: int) -> None:
        """Forget tracks absent for the hysteresis window, re-arming announcement."""
        for track_id, state in list(self._tracks.items()):
            if frame - state.last_seen_frame >= self.clear_frames:
                del self._tracks[track_id]
                # A queued cue about an object that has left is stale, not pending.
                self._queue = [event for event in self._queue if event.track_id != track_id]

    def _enqueue(self, event: AlertEvent) -> None:
        self._queue.append(event)

    def _drain(self) -> list[AlertEvent]:
        """Apply DANGER pre-emption and the NOTICE "only if the queue is idle" rule."""
        if not self._queue:
            return []
        danger = [event for event in self._queue if event.tier == "danger"]
        if danger:
            # "DANGER always pre-empts the queue and interrupts current speech."
            for event in self._queue:
                if event.tier != "danger":
                    self.log.append(replace(event, preempted=True))
            self._queue = []
            return self._speak(danger)
        warnings = [event for event in self._queue if event.tier == "warning"]
        if warnings:
            # NOTICEs stay queued: the queue is not idle this frame.
            self._queue = [event for event in self._queue if event.tier != "warning"]
            return self._speak(warnings)
        notices = list(self._queue)
        self._queue = []
        return self._speak(notices)

    def _speak(self, events: list[AlertEvent]) -> list[AlertEvent]:
        spoken = []
        for event in events:
            state = self._tracks.get(event.track_id)
            if state is not None:
                state.announced = True
            said = replace(event, spoken=True, spoken_frame=self._frame)
            self.log.append(said)
            spoken.append(said)
        return spoken

    # --- introspection ---------------------------------------------------
    @property
    def pending(self) -> list[AlertEvent]:
        """Events waiting for an idle queue (NOTICEs held behind a WARNING)."""
        return list(self._queue)

    def tracked_ids(self) -> set[int]:
        return set(self._tracks)


__all__ = [
    "APPROACH_GROWTH",
    "APPROACH_WINDOW_FRAMES",
    "CLEAR_FRAMES",
    "FAST_GROWTH",
    "FAR_RATIO",
    "MAX_LATENCY_MS",
    "NEAR_RATIO",
    "PERSIST_FRAMES",
    "AlertEvent",
    "Detection",
    "DistanceBucket",
    "Tier",
    "Triage",
    "Zone",
    "distance_bucket_for",
    "earcon_for",
    "tier_for",
    "utterance_for",
    "zone_for",
]
