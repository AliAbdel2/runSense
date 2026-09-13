"""Deterministic triage-logic fixtures. Not a computer-vision measurement.

Every sequence below is *procedurally generated Python*: hand-placed bounding
boxes fed straight into :class:`runsense.triage.Triage`. No camera, no video, no
model inference, no labelled footage - none of those exist in this environment.

So be exact about what a green run here means and what it does not:

Tested                       | Not tested
-----------------------------|-----------------------------------------------
zone thirds, NEAR/MID/FAR    | whether YOLO11n finds the object at all
buckets, tier table, the     | zone/bucket accuracy against real ground truth
3-frame debounce, the        | false-alert rate on real streets
15-frame re-announce window, | end-to-end capture-to-audio latency
DANGER pre-emption           | anything about a phone, a camera or a headset

The plan's 40-clip golden set, its recall target and its <400 ms end-to-end
budget remain unmeasured. Do not quote a number from this harness as evidence
about any of them.

Run standalone::

    python -m runsense.perception_eval
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .triage import AlertEvent, Detection, Triage

FRAME_WIDTH = 640.0
FRAME_HEIGHT = 384.0
BOX_WIDTH_RATIO = 0.12

STATUS = "triage_logic_tested"
DETAIL = (
    "Zone, distance-bucket, tier, 3-frame debounce, 15-frame re-announcement and DANGER "
    "pre-emption logic are verified against procedurally generated synthetic detection "
    "sequences built from the plan's own trigger table. No camera, no model inference and no "
    "labelled footage are involved: detection recall, zone accuracy, false-alert rate and "
    "end-to-end capture-to-audio latency remain unmeasured."
)
UNMEASURED = [
    "detection recall on real footage",
    "zone and distance accuracy against ground truth",
    "false-alert rate",
    "end-to-end capture-to-audio latency (the plan's <400 ms DANGER budget)",
    "on-device (phone) execution",
]


def detection(frame_index: int, track_id: int, obj_class: str, center_x_ratio: float,
              height_ratio: float) -> Detection:
    """One synthetic box placed by its centre-x fraction and height fraction."""
    box_width = BOX_WIDTH_RATIO * FRAME_WIDTH
    center_x = center_x_ratio * FRAME_WIDTH
    box_height = height_ratio * FRAME_HEIGHT
    top = (FRAME_HEIGHT - box_height) / 2
    return Detection(frame_index=frame_index, track_id=track_id, obj_class=obj_class,
                     x1=center_x - box_width / 2, y1=top, x2=center_x + box_width / 2,
                     y2=top + box_height, frame_width=FRAME_WIDTH, frame_height=FRAME_HEIGHT)


def growing(start: float, rate: float, count: int) -> list[float]:
    """A height-proxy series growing at a fixed rate per frame (an approach)."""
    return [round(start * rate ** step, 6) for step in range(count)]


def steady(value: float, count: int) -> list[float]:
    return [value] * count


class Sequence:
    """A frame-indexed list of detections; index 0 is frame 0, gaps are empty frames."""

    def __init__(self, length: int) -> None:
        self.frames: list[list[Detection]] = [[] for _ in range(length)]

    def add(self, track_id: int, obj_class: str, center_x_ratio: float, ratios: list[float],
            start: int = 0) -> "Sequence":
        for offset, ratio in enumerate(ratios):
            index = start + offset
            self.frames[index].append(detection(index, track_id, obj_class, center_x_ratio, ratio))
        return self


@dataclass(frozen=True)
class Fixture:
    name: str
    plan_rule: str
    sequence: Sequence
    expected: list[tuple[int, str, str]]  # (frame_index, tier, utterance) per spoken alert
    note: str = ""
    extra: Callable[[list[AlertEvent], Triage], tuple[bool, str]] | None = field(default=None)


def _observed(events: list[AlertEvent]) -> list[tuple[int, str, str]]:
    return [(event.frame_index, event.tier, event.utterance) for event in events]


def fixtures() -> list[Fixture]:
    """One sequence per row of the plan's trigger table, plus the timing rules."""
    cases: list[Fixture] = []

    # DANGER: CENTER + NEAR.
    cases.append(Fixture(
        name="center_near_is_danger",
        plan_rule="DANGER: CENTER + NEAR",
        sequence=Sequence(8).add(1, "person", 0.50, steady(0.60, 8)),
        expected=[(2, "danger", "Stop - person ahead")],
        note="Announced once, on the third consecutive frame, not once per frame."))

    # DANGER: any zone NEAR and approaching fast.
    cases.append(Fixture(
        name="near_approaching_fast_off_centre_is_danger",
        plan_rule="DANGER: any zone NEAR and approaching fast",
        sequence=Sequence(6).add(2, "person", 0.15, growing(0.46, 1.13, 6)),
        expected=[(2, "danger", "Stop - person left")],
        note="A left-zone NEAR object closing fast is promoted past WARNING."))

    # WARNING: LEFT/RIGHT + NEAR.
    cases.append(Fixture(
        name="left_near_is_warning",
        plan_rule="WARNING: LEFT/RIGHT + NEAR",
        sequence=Sequence(8).add(3, "person", 0.15, steady(0.60, 8)),
        expected=[(2, "warning", "person left")],
        note="Stationary relative distance, so no promotion to DANGER."))

    # NOTICE: MID, not approaching.
    cases.append(Fixture(
        name="mid_not_approaching_is_notice",
        plan_rule="NOTICE: MID, not approaching",
        sequence=Sequence(8).add(4, "bicycle", 0.80, steady(0.30, 8)),
        expected=[(2, "notice", "bicycle far right")],
        note="Soft cue only; the queue is idle so it is spoken on the same frame."))

    # WARNING: MID and approaching (Figure 3's one-tier promotion).
    cases.append(Fixture(
        name="mid_approaching_is_warning",
        plan_rule="WARNING: CENTER + MID approaching (Figure 3: mid+approaching = WARNING)",
        sequence=Sequence(7).add(5, "person", 0.50, growing(0.22, 1.08, 7)),
        expected=[(2, "warning", "person ahead")],
        note="Growing bbox height promotes a NOTICE to a WARNING."))

    # silent: FAR.
    far = Fixture(
        name="far_stays_silent",
        plan_rule="silent: FAR - logged for eval, never spoken",
        sequence=Sequence(10).add(6, "car", 0.50, steady(0.10, 10)),
        expected=[],
        note="Nothing is spoken; one silent record is logged for evaluation.",
        extra=lambda events, triage: (
            any(entry.tier == "silent" and not entry.spoken for entry in triage.log),
            "silent decision logged" if any(entry.tier == "silent" for entry in triage.log)
            else "no silent record was logged"))
    cases.append(far)

    # Debounce: fewer than 3 frames of persistence is never announced.
    cases.append(Fixture(
        name="under_three_frames_is_never_announced",
        plan_rule="Debounce: an object must persist 3 frames before it is announced",
        sequence=Sequence(20).add(7, "person", 0.50, steady(0.60, 2)),
        expected=[],
        note="A two-frame CENTER+NEAR flicker would otherwise fire a DANGER alert."))

    # Hysteresis: 15 clear frames re-arm the announcement.
    reappearing = Sequence(32).add(8, "person", 0.50, steady(0.60, 5), start=0)
    reappearing.add(8, "person", 0.50, steady(0.60, 5), start=25)
    cases.append(Fixture(
        name="reannounced_after_fifteen_clear_frames",
        plan_rule="Hysteresis: must leave for 15 frames before it can be re-announced",
        sequence=reappearing,
        expected=[(2, "danger", "Stop - person ahead"), (27, "danger", "Stop - person ahead")],
        note="Absent for 20 frames, so the second appearance debounces and speaks again."))

    # Hysteresis, the other direction: a shorter gap does not re-arm it.
    blinking = Sequence(32).add(9, "person", 0.50, steady(0.60, 5), start=0)
    blinking.add(9, "person", 0.50, steady(0.60, 5), start=15)
    cases.append(Fixture(
        name="not_reannounced_after_a_ten_frame_gap",
        plan_rule="Hysteresis: a gap shorter than 15 frames must not re-announce",
        sequence=blinking,
        expected=[(2, "danger", "Stop - person ahead")],
        note="Absent for 10 frames only, so the same object is not repeated."))

    # DANGER pre-empts a queued WARNING in the same frame.
    contested = Sequence(8).add(10, "person", 0.15, steady(0.60, 8))  # LEFT + NEAR -> WARNING
    contested.add(11, "car", 0.50, steady(0.60, 8))                   # CENTER + NEAR -> DANGER
    cases.append(Fixture(
        name="danger_preempts_queued_warning",
        plan_rule="DANGER always pre-empts the queue and interrupts current speech",
        sequence=contested,
        expected=[(2, "danger", "Stop - car ahead"), (3, "warning", "person left")],
        note=("The WARNING raised on the same frame is dropped from the queue, logged as "
              "pre-empted, and only re-raised on the next frame once the queue is idle - the "
              "obstacle is still there, so it is deferred rather than discarded."),
        extra=lambda events, triage: (
            any(entry.preempted and entry.tier == "warning" and entry.frame_index == 2
                for entry in triage.log),
            "pre-empted WARNING recorded in the log")))

    return cases


def run_fixture(fixture: Fixture) -> dict:
    """Replay one sequence through Triage and compare against the expected alerts."""
    triage = Triage()
    spoken: list[AlertEvent] = []
    for frame_index, detections in enumerate(fixture.sequence.frames):
        triage.observe_all(detections)
        spoken.extend(triage.emit(frame_index))
    observed = _observed(spoken)
    passed = observed == fixture.expected
    detail = fixture.note
    if fixture.extra is not None:
        extra_passed, extra_detail = fixture.extra(spoken, triage)
        passed = passed and bool(extra_passed)
        detail = f"{detail} {extra_detail}".strip()
    return {"name": fixture.name, "plan_rule": fixture.plan_rule, "passed": passed,
            "frames": len(fixture.sequence.frames),
            "expected": [list(item) for item in fixture.expected],
            "observed": [list(item) for item in observed], "detail": detail}


def evaluate_perception() -> dict:
    """Report on the triage logic only, in wording that cannot be mistaken for CV metrics."""
    results = [run_fixture(fixture) for fixture in fixtures()]
    return {"status": STATUS, "detail": DETAIL,
            "fixtures_passed": sum(1 for result in results if result["passed"]),
            "fixtures_total": len(results),
            "evidence": "synthetic_detection_sequences",
            "unmeasured": list(UNMEASURED),
            "results": results}


if __name__ == "__main__":
    import json

    report = evaluate_perception()
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["fixtures_passed"] == report["fixtures_total"] else 1)
