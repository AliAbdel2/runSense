"""Baseline derivation and the four hard safety rules for a generated plan.

Pure functions only: no DB session, no HTTP, no LLM. Callers (plan_service.py)
fetch the activities and pass plain data in; everything here is deterministic
and independently unit-testable.
"""
from __future__ import annotations
import math
from datetime import date, timedelta

TRAILING_DAYS = 21  # 3 weeks

# Conservative starting volume when there is no recent activity history to
# derive one from — roughly three light easy runs a week, not a presumption
# of any real fitness level.
DEFAULT_BASELINE_KM = 10.0

HARD_KINDS = {"intervals", "long"}
# Rule 3's literal spec: a hard session is safe without an accepted guide only
# on these venues.
GUIDE_EXEMPT_VENUES = {"track", "treadmill"}
MAX_SPOKEN_SUMMARY_WORDS = 25
VOLUME_CAP_MULTIPLIER = 1.10


def compute_baseline(activities: list, week_start: date) -> dict:
    """The trailing 3-week average weekly distance.

    `activities` is assumed already filtered to the trailing window (the
    caller does that with a repository query); this function only needs
    `week_start` to work out how many of the 3 weeks are actually covered.
    Each activity needs `.date` and `.km` attributes (an ORM Activity row
    satisfies this, and so does any plain object with those two attributes).
    """
    if not activities:
        return {"km": DEFAULT_BASELINE_KM, "source": "defaulted", "weeks_used": 0, "activity_count": 0}

    total_km = sum(a.km for a in activities)
    earliest = min(a.date for a in activities)
    # How far back real data actually goes, clamped to the 3-week window.
    weeks_used = min(3, max(1, math.ceil((week_start - earliest).days / 7)))
    return {
        "km": round(total_km / weeks_used, 2),
        "source": "derived",
        "weeks_used": weeks_used,
        "activity_count": len(activities),
    }


def _session_date(session: dict) -> date:
    value = session["date"]
    return date.fromisoformat(value) if isinstance(value, str) else value


def check_weekly_volume_cap(plan: dict) -> dict:
    baseline_km = plan["baseline_km"]
    week_km = plan["week_km"]
    cap = round(baseline_km * VOLUME_CAP_MULTIPLIER, 2)
    passed = week_km <= cap + 1e-9
    return {
        "name": "weekly_volume_cap",
        "passed": passed,
        "detail": f"{week_km:g} km planned vs a {baseline_km:g} km baseline (110% cap is {cap:g} km).",
    }


def check_hard_day_spacing(plan: dict) -> dict:
    hard_dates = sorted(_session_date(s) for s in plan["sessions"] if s["kind"] in HARD_KINDS)
    consecutive = any((b - a).days <= 1 for a, b in zip(hard_dates, hard_dates[1:]))
    has_rest = any(s["kind"] == "rest" for s in plan["sessions"])
    passed = not consecutive and has_rest
    if consecutive:
        detail = "Two hard sessions fall on consecutive days."
    elif not has_rest:
        detail = "No full rest day in the week."
    else:
        detail = "Hard sessions are spaced out and at least one rest day is scheduled."
    return {"name": "hard_day_spacing", "passed": passed, "detail": detail}


def check_guide_requirement(plan: dict) -> dict:
    violations = [
        s["id"] for s in plan["sessions"]
        if s["kind"] in HARD_KINDS and s["guide_status"] != "accepted" and s["venue"] not in GUIDE_EXEMPT_VENUES
    ]
    passed = not violations
    detail = ("Every hard session has an accepted guide or a track/treadmill venue." if passed
             else f"{len(violations)} hard session(s) lack an accepted guide on a non-exempt venue.")
    return {"name": "guide_requirement", "passed": passed, "detail": detail}


def check_spoken_summary_length(plan: dict) -> dict:
    violations = [s["id"] for s in plan["sessions"] if len(s["spoken_summary"].split()) > MAX_SPOKEN_SUMMARY_WORDS]
    passed = not violations
    detail = (f"All spoken summaries are {MAX_SPOKEN_SUMMARY_WORDS} words or fewer." if passed
             else f"{len(violations)} spoken summary(ies) exceed {MAX_SPOKEN_SUMMARY_WORDS} words.")
    return {"name": "spoken_summary_length", "passed": passed, "detail": detail}


def validate_plan(plan: dict) -> dict:
    checks = [
        check_weekly_volume_cap(plan),
        check_hard_day_spacing(plan),
        check_guide_requirement(plan),
        check_spoken_summary_length(plan),
    ]
    return {"passed": all(c["passed"] for c in checks), "checks": checks}
