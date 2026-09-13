import asyncio
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from runsense.evaluation import evaluate
from runsense.models import Activity, PlanRequest
from runsense.planner import baseline_km, demo_history, generate_plan, guide_confirmations, validate_plan

WEEK = date(2026, 9, 14)


def test_scenario_suite():
    report = asyncio.run(evaluate())
    assert report["passed"] == report["total"] == 16, report
    # Perception is a separate, narrower claim: the triage logic is tested against
    # synthetic fixtures; real-world CV accuracy and latency are still unmeasured.
    perception = report["perception"]
    assert perception["status"] == "triage_logic_tested"
    assert perception["fixtures_passed"] == perception["fixtures_total"] > 0, perception
    assert "unmeasured" in perception["detail"]


def test_baseline_uses_complete_weeks_and_counts_missing_weeks_as_zero():
    history = [Activity(date=WEEK - timedelta(days=1), km=12, source="synthetic"),
               Activity(date=WEEK, km=60, source="synthetic"),
               Activity(date=WEEK - timedelta(days=22), km=100, source="synthetic"),
               Activity(date=WEEK - timedelta(days=3), km=9, completed=False, source="synthetic")]
    assert baseline_km(history, WEEK) == 4


@pytest.mark.parametrize("status", ["pending", "declined", "not_required"])
def test_track_requires_actual_acceptance(status):
    history = demo_history(WEEK)
    guides = {(WEEK + timedelta(days=1)).isoformat(): status}
    plan = generate_plan(history, WEEK, guides=guides)
    assert plan.sessions[1].venue == "treadmill"
    plan.sessions[1].venue = "track"
    plan.sessions[1].guide_status = "accepted"
    assert not validate_plan(plan, history, guides)["passed"]


@pytest.mark.parametrize("mutation", ["duplicate_date", "long_speech", "back_to_back", "invented_id", "rest_with_distance"])
def test_invalid_proposals_fail_hard_gate(mutation):
    history = demo_history(WEEK)
    guides = guide_confirmations(WEEK, "baseline")
    plan = generate_plan(history, WEEK, guides=guides)
    if mutation == "duplicate_date":
        plan.sessions[0].date = plan.sessions[1].date
    elif mutation == "long_speech":
        plan.sessions[1].spoken_summary = "word " * 26
    elif mutation == "back_to_back":
        plan.sessions[6].kind = "intervals"
    elif mutation == "invented_id":
        plan.sessions[1].id = "arbitrary"
    else:
        plan.sessions[0].km = 1
    assert not validate_plan(plan, history, guides)["passed"]


@pytest.mark.parametrize("km", [-1, float("inf"), float("nan")])
def test_invalid_activity_distance_rejected(km):
    with pytest.raises(ValidationError):
        Activity(date=WEEK, km=km, source="synthetic")


def test_no_history_does_not_invent_training_load():
    plan = generate_plan([], WEEK)
    assert plan.week_km == 0
    assert all(s.kind == "rest" for s in plan.sessions)

