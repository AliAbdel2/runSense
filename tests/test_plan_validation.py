from datetime import date, timedelta

from app.models import Activity
from app.services.plan_validation import (
    DEFAULT_BASELINE_KM,
    check_guide_requirement,
    check_hard_day_spacing,
    check_spoken_summary_length,
    check_weekly_volume_cap,
    compute_baseline,
    validate_plan,
)

WEEK_START = date(2026, 9, 14)  # a Monday


def _activity(day, km):
    return Activity(id=f"a-{day.isoformat()}", athlete_id="sara", date=day, km=km)


def _base_plan(**overrides):
    sessions = [
        {"id": "rest-mon", "date": "2026-09-14", "kind": "rest", "km": 0, "venue": "home", "guide_status": "not_required", "spoken_summary": "Rest day. No running scheduled."},
        {"id": "intervals-tue", "date": "2026-09-15", "kind": "intervals", "km": 5.2, "venue": "track", "guide_status": "accepted", "spoken_summary": "Intervals run for 5.2 kilometres at the track."},
        {"id": "rest-wed", "date": "2026-09-16", "kind": "rest", "km": 0, "venue": "home", "guide_status": "not_required", "spoken_summary": "Rest day. No running scheduled."},
        {"id": "easy-thu", "date": "2026-09-17", "kind": "easy", "km": 4.2, "venue": "treadmill", "guide_status": "not_required", "spoken_summary": "Easy run for 4.2 kilometres at the treadmill."},
        {"id": "rest-fri", "date": "2026-09-18", "kind": "rest", "km": 0, "venue": "home", "guide_status": "not_required", "spoken_summary": "Rest day. No running scheduled."},
        {"id": "long-sat", "date": "2026-09-19", "kind": "long", "km": 10.6, "venue": "track", "guide_status": "accepted", "spoken_summary": "Long run for 10.6 kilometres at the track."},
        {"id": "rest-sun", "date": "2026-09-20", "kind": "rest", "km": 0, "venue": "home", "guide_status": "not_required", "spoken_summary": "Rest day. No running scheduled."},
    ]
    plan = {"week_start": WEEK_START.isoformat(), "baseline_km": 20.0, "week_km": round(sum(s["km"] for s in sessions), 1), "sessions": sessions}
    plan.update(overrides)
    return plan


def test_compute_baseline_averages_seeded_activities_over_three_weeks():
    activities = [
        _activity(WEEK_START - timedelta(days=21), 15.0),
        _activity(WEEK_START - timedelta(days=14), 18.0),
        _activity(WEEK_START - timedelta(days=7), 21.0),
    ]
    baseline = compute_baseline(activities, WEEK_START)
    assert baseline == {"km": 18.0, "source": "derived", "weeks_used": 3, "activity_count": 3}


def test_compute_baseline_defaults_when_athlete_has_no_activities():
    baseline = compute_baseline([], WEEK_START)
    assert baseline == {"km": DEFAULT_BASELINE_KM, "source": "defaulted", "weeks_used": 0, "activity_count": 0}


def test_compute_baseline_averages_over_partial_window_under_three_weeks():
    activities = [_activity(WEEK_START - timedelta(days=10), 8.0), _activity(WEEK_START - timedelta(days=3), 6.0)]
    baseline = compute_baseline(activities, WEEK_START)
    assert baseline["source"] == "derived"
    assert baseline["weeks_used"] == 2  # ceil(10 / 7)
    assert baseline["activity_count"] == 2
    assert baseline["km"] == 7.0  # (8 + 6) / 2


def test_validate_plan_passes_on_a_well_formed_plan():
    result = validate_plan(_base_plan())
    assert result["passed"] is True
    assert all(check["passed"] for check in result["checks"])


def test_rule_1_weekly_volume_cap_fails_when_over_110_percent_of_baseline():
    plan = _base_plan(baseline_km=10.0, week_km=15.0)  # 150% of baseline
    result = check_weekly_volume_cap(plan)
    assert result["passed"] is False
    assert result["name"] == "weekly_volume_cap"


def test_rule_2_hard_day_spacing_fails_on_consecutive_hard_sessions():
    plan = _base_plan()
    plan["sessions"][2] = {**plan["sessions"][2], "kind": "intervals", "km": 5.0, "venue": "track", "guide_status": "accepted"}  # Wednesday now hard too, next to Tuesday's intervals
    result = check_hard_day_spacing(plan)
    assert result["passed"] is False
    assert result["name"] == "hard_day_spacing"


def test_rule_2_hard_day_spacing_fails_when_no_rest_day_exists():
    plan = _base_plan()
    for session in plan["sessions"]:
        if session["kind"] == "rest":
            session["kind"], session["km"], session["venue"] = "easy", 3.0, "treadmill"
    result = check_hard_day_spacing(plan)
    assert result["passed"] is False


def test_rule_3_guide_requirement_fails_for_unguided_hard_session_off_exempt_venue():
    plan = _base_plan()
    plan["sessions"][1] = {**plan["sessions"][1], "venue": "park", "guide_status": "pending"}
    result = check_guide_requirement(plan)
    assert result["passed"] is False
    assert result["name"] == "guide_requirement"


def test_rule_4_spoken_summary_length_fails_over_25_words():
    plan = _base_plan()
    plan["sessions"][1] = {**plan["sessions"][1], "spoken_summary": " ".join(["word"] * 26)}
    result = check_spoken_summary_length(plan)
    assert result["passed"] is False
    assert result["name"] == "spoken_summary_length"
