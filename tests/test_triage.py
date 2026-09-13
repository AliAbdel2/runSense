"""Pure-logic tests for obstacle triage. No model, no camera, no heavy imports."""

import pytest

from runsense.triage import (
    CLEAR_FRAMES,
    PERSIST_FRAMES,
    AlertEvent,
    Detection,
    Triage,
    distance_bucket_for,
    earcon_for,
    tier_for,
    utterance_for,
    zone_for,
)

WIDTH = 640.0
HEIGHT = 384.0


def box(frame_index=0, track_id=1, obj_class="person", center_x_ratio=0.5, height_ratio=0.6):
    """One synthetic detection placed by centre-x fraction and height fraction."""
    box_width = 0.1 * WIDTH
    center_x = center_x_ratio * WIDTH
    box_height = height_ratio * HEIGHT
    top = (HEIGHT - box_height) / 2
    return Detection(frame_index=frame_index, track_id=track_id, obj_class=obj_class,
                     x1=center_x - box_width / 2, y1=top, x2=center_x + box_width / 2,
                     y2=top + box_height, frame_width=WIDTH, frame_height=HEIGHT)


def play(triage, frames):
    """Feed a list of per-frame detection lists; return every spoken event."""
    spoken = []
    for index, detections in enumerate(frames):
        triage.observe_all(detections)
        spoken.extend(triage.emit(index))
    return spoken


def held(track_id, center_x_ratio, height_ratio, count, start=0, obj_class="person"):
    return [[box(start + offset, track_id, obj_class, center_x_ratio, height_ratio)]
            for offset in range(count)]


# --- Detection ------------------------------------------------------------


def test_detection_rejects_a_zero_sized_frame():
    with pytest.raises(ValueError):
        Detection(frame_index=0, track_id=1, obj_class="person", x1=0, y1=0, x2=10, y2=10,
                  frame_width=0, frame_height=HEIGHT)


def test_detection_ratios_are_derived_from_the_frame():
    detection = box(center_x_ratio=0.25, height_ratio=0.5)
    assert detection.center_x_ratio == pytest.approx(0.25)
    assert detection.height_ratio == pytest.approx(0.5)


# --- zone_for -------------------------------------------------------------


@pytest.mark.parametrize("center_x_ratio,expected", [
    (0.0, "left"), (0.10, "left"), (0.3333, "left"),
    (1 / 3, "center"), (0.5, "center"), (2 / 3, "center"),
    (0.67, "right"), (0.9, "right"), (1.0, "right"),
])
def test_zone_splits_the_frame_into_thirds(center_x_ratio, expected):
    assert zone_for(box(center_x_ratio=center_x_ratio)) == expected


# --- distance_bucket_for --------------------------------------------------


@pytest.mark.parametrize("height_ratio,expected", [
    (0.9, "near"), (0.46, "near"),
    (0.45, "mid"), (0.30, "mid"), (0.20, "mid"),
    (0.199, "far"), (0.05, "far"),
])
def test_distance_bucket_uses_the_plan_thresholds(height_ratio, expected):
    assert distance_bucket_for(box(height_ratio=height_ratio)) == expected


# --- tier_for: the plan's whole trigger table ------------------------------


@pytest.mark.parametrize("zone", ["left", "center", "right"])
def test_far_is_always_silent_even_when_approaching(zone):
    assert tier_for(zone, "far", approaching=True, approaching_fast=True) == "silent"


def test_center_near_is_danger_without_any_velocity():
    assert tier_for("center", "near") == "danger"


@pytest.mark.parametrize("zone", ["left", "right"])
def test_side_near_is_warning_until_it_closes_fast(zone):
    assert tier_for(zone, "near") == "warning"
    assert tier_for(zone, "near", approaching=True) == "warning"
    assert tier_for(zone, "near", approaching=True, approaching_fast=True) == "danger"


@pytest.mark.parametrize("zone", ["left", "center", "right"])
def test_mid_is_notice_unless_approaching(zone):
    assert tier_for(zone, "mid") == "notice"
    assert tier_for(zone, "mid", approaching=True) == "warning"


def test_utterances_and_earcons_follow_the_zone_mapping():
    assert utterance_for("person", "center", "danger") == "Stop - person ahead"
    assert utterance_for("person", "left", "warning") == "person left"
    assert utterance_for("bicycle", "right", "notice") == "bicycle far right"
    assert utterance_for("car", "center", "notice") == "car ahead"
    assert utterance_for("car", "center", "silent") == ""
    assert earcon_for("center", "danger") == "double_tone"
    assert earcon_for("left", "warning") == "panned_tone_left"
    assert earcon_for("right", "notice") == "soft_cue"


def test_events_carry_the_per_tier_latency_budget():
    spoken = play(Triage(), held(1, 0.5, 0.6, 4))
    assert [event.max_latency_ms for event in spoken] == [400]


# --- debounce -------------------------------------------------------------


def test_nothing_is_announced_before_three_consecutive_frames():
    triage = Triage()
    frames = held(1, 0.5, 0.6, PERSIST_FRAMES)
    assert play(triage, frames[:PERSIST_FRAMES - 1]) == []
    spoken = play(Triage(), frames)
    assert [(event.frame_index, event.tier) for event in spoken] == [(2, "danger")]


def test_a_flickering_object_never_reaches_the_persistence_threshold():
    # Present on every other frame: the streak resets, so it is never announced.
    frames = [[box(index, 1, "person", 0.5, 0.6)] if index % 2 == 0 else [] for index in range(20)]
    assert play(Triage(), frames) == []


def test_a_persistent_object_is_announced_once_not_once_per_frame():
    spoken = play(Triage(), held(1, 0.5, 0.6, 30))
    assert len(spoken) == 1


# --- hysteresis -----------------------------------------------------------


def test_reannounced_only_after_fifteen_clear_frames():
    gap = CLEAR_FRAMES
    frames = held(1, 0.5, 0.6, 5) + [[] for _ in range(gap)]
    frames += [[box(len(frames) + offset, 1, "person", 0.5, 0.6)] for offset in range(5)]
    spoken = play(Triage(), frames)
    assert [event.tier for event in spoken] == ["danger", "danger"]
    assert spoken[1].frame_index == 5 + gap + 2


def test_not_reannounced_after_a_shorter_gap():
    gap = CLEAR_FRAMES - 1
    frames = held(1, 0.5, 0.6, 5) + [[] for _ in range(gap)]
    frames += [[box(len(frames) + offset, 1, "person", 0.5, 0.6)] for offset in range(5)]
    assert len(play(Triage(), frames)) == 1


def test_an_absent_track_is_forgotten_so_it_debounces_again():
    triage = Triage()
    play(triage, held(1, 0.5, 0.6, 5) + [[] for _ in range(CLEAR_FRAMES)])
    assert triage.tracked_ids() == set()


# --- approaching ----------------------------------------------------------


def test_growing_bbox_promotes_a_mid_object_to_warning():
    ratios = [0.22 * 1.08 ** step for step in range(6)]
    frames = [[box(index, 1, "person", 0.5, ratio)] for index, ratio in enumerate(ratios)]
    spoken = play(Triage(), frames)
    assert [(event.tier, event.approaching) for event in spoken] == [("warning", True)]


def test_a_steady_mid_object_is_only_a_notice():
    spoken = play(Triage(), held(1, 0.5, 0.30, 6))
    assert [(event.tier, event.approaching) for event in spoken] == [("notice", False)]


def test_a_shrinking_bbox_is_not_approaching():
    ratios = [0.40 * 0.9 ** step for step in range(6)]
    frames = [[box(index, 1, "person", 0.5, ratio)] for index, ratio in enumerate(ratios)]
    spoken = play(Triage(), frames)
    assert [(event.tier, event.approaching) for event in spoken] == [("notice", False)]


def test_a_side_object_closing_fast_is_promoted_to_danger():
    ratios = [0.46 * 1.13 ** step for step in range(5)]
    frames = [[box(index, 1, "person", 0.15, ratio)] for index, ratio in enumerate(ratios)]
    spoken = play(Triage(), frames)
    assert [(event.tier, event.utterance) for event in spoken] == [("danger", "Stop - person left")]


# --- silent tier ----------------------------------------------------------


def test_far_objects_are_logged_but_never_spoken():
    triage = Triage()
    assert play(triage, held(1, 0.5, 0.10, 10)) == []
    silent = [entry for entry in triage.log if entry.tier == "silent"]
    assert len(silent) == 1 and not silent[0].spoken and silent[0].utterance == ""


def test_a_far_object_that_drifts_into_mid_is_announced_immediately():
    # Just below the 0.20 boundary, then just above it: the bucket changes but the
    # growth is far too small to count as approaching.
    frames = held(1, 0.8, 0.199, 5, obj_class="bicycle")
    frames += [[box(5 + offset, 1, "bicycle", 0.8, 0.201)] for offset in range(3)]
    spoken = play(Triage(), frames)
    # Persistence was already satisfied while it was FAR, so no second debounce.
    assert [(event.frame_index, event.tier) for event in spoken] == [(5, "notice")]


def test_a_far_object_that_closes_rapidly_into_mid_is_promoted():
    frames = held(1, 0.8, 0.10, 5, obj_class="bicycle")
    frames += [[box(5 + offset, 1, "bicycle", 0.8, 0.30)] for offset in range(3)]
    spoken = play(Triage(), frames)
    # Tripling the height proxy in one frame is exactly what "approaching" means.
    assert [(event.frame_index, event.tier) for event in spoken] == [(5, "warning")]


# --- queue priority and pre-emption ---------------------------------------


def test_danger_preempts_a_warning_raised_in_the_same_frame():
    frames = [[box(index, 1, "person", 0.15, 0.6), box(index, 2, "car", 0.5, 0.6)]
              for index in range(3)]
    triage = Triage()
    spoken = play(triage, frames)
    assert [(event.tier, event.obj_class) for event in spoken] == [("danger", "car")]
    preempted = [entry for entry in triage.log if entry.preempted]
    assert [(entry.tier, entry.obj_class, entry.frame_index) for entry in preempted] == [
        ("warning", "person", 2)]


def test_a_preempted_warning_is_re_raised_once_the_queue_is_idle():
    frames = [[box(index, 1, "person", 0.15, 0.6), box(index, 2, "car", 0.5, 0.6)]
              for index in range(6)]
    spoken = play(Triage(), frames)
    assert [(event.frame_index, event.tier, event.obj_class) for event in spoken] == [
        (2, "danger", "car"), (3, "warning", "person")]


def test_a_notice_waits_behind_a_warning_and_is_spoken_when_the_queue_is_idle():
    frames = [[box(index, 1, "person", 0.15, 0.6), box(index, 2, "bicycle", 0.8, 0.30)]
              for index in range(6)]
    triage = Triage()
    spoken = play(triage, frames)
    # Both are raised on frame 2; the soft cue waits a frame for an idle queue.
    assert [(event.frame_index, event.spoken_frame, event.tier) for event in spoken] == [
        (2, 2, "warning"), (2, 3, "notice")]
    assert triage.pending == []


def test_a_queued_notice_is_dropped_when_its_object_leaves():
    # A stream of people, each visible for three frames, keeps a WARNING draining
    # on every frame, so the bicycle's NOTICE never gets an idle queue. The bike
    # leaves after frame 2 and the stale cue is discarded, not spoken later.
    frames = []
    for index in range(CLEAR_FRAMES + 6):
        detections = [box(index, 100 + start, "person", 0.15, 0.6)
                      for start in range(max(0, index - 2), index + 1)]
        if index < 3:
            detections.append(box(index, 2, "bicycle", 0.8, 0.30))
        frames.append(detections)
    triage = Triage()
    spoken = play(triage, frames)
    assert [event.tier for event in spoken] == ["warning"] * len(spoken)
    assert triage.pending == []
    assert 2 not in triage.tracked_ids()


def test_emit_advances_the_frame_counter_without_detections():
    triage = Triage()
    play(triage, held(1, 0.5, 0.6, 4))
    for _ in range(CLEAR_FRAMES):
        assert triage.emit() == []
    assert triage.tracked_ids() == set()


def test_events_serialize_for_the_alert_stream():
    spoken = play(Triage(), held(1, 0.5, 0.6, 4))
    payload = spoken[0].to_dict()
    assert isinstance(spoken[0], AlertEvent)
    assert payload["tier"] == "danger" and payload["spoken"] is True
    assert payload["zone"] == "center" and payload["distance"] == "near"
    assert payload["frame_index"] == payload["spoken_frame"] == 2
    assert set(payload) == {"frame_index", "spoken_frame", "track_id", "obj_class", "zone",
                            "distance", "tier", "approaching", "utterance", "earcon",
                            "max_latency_ms", "spoken", "preempted"}
