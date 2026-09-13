"""Pure planning rules, deliberately separate from model-generated suggestions.

The volume cap is a configurable prototype constraint, not injury-prevention evidence.
Guide availability is never treated as a confirmed attendance response.
"""
import hashlib
from datetime import date, timedelta

from .models import Activity, Plan, Session


def stable_id(*parts: object) -> str:
    return hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:32]


def next_monday(today: date | None = None) -> date:
    today = today or date.today()
    return today + timedelta(days=7 - today.weekday())


def demo_history(week_start: date) -> list[Activity]:
    return [
        Activity(date=week_start - timedelta(weeks=w) + timedelta(days=d), km=km, source="synthetic")
        for w, total in [(3, 18.0), (2, 20.0), (1, 19.0)]
        for d, km in [(1, total * .25), (3, total * .25), (5, total * .35), (6, total * .15)]
    ]


def baseline_km(history: list[Activity], week_start: date) -> float:
    # Always use three complete weeks, including zero-volume weeks.
    return round(sum(a.km for a in history if a.completed and
                     week_start - timedelta(days=21) <= a.date < week_start) / 3, 2)


def guide_confirmations(week_start: date, scenario: str, demo: bool = True) -> dict[str, str]:
    confirmations = {(week_start + timedelta(days=d)).isoformat(): "accepted" for d in (1, 5)} if demo else {}
    if scenario == "guide_cancelled":
        confirmations[(week_start + timedelta(days=1)).isoformat()] = "declined"
    return confirmations


def generate_plan(history: list[Activity], week_start: date, scenario: str = "baseline",
                  guides: dict[str, str] | None = None, *, athlete_id: str = "sara", athlete_name: str = "Sara") -> Plan:
    guides = guides or {}
    baseline = baseline_km(history, week_start)
    # Never auto-prescribe starting volume from an empty history.
    target = round(baseline * (.8 if scenario == "missed_session" else 1), 1)
    if baseline < 1:
        target = 0
    weights = {1: .25, 3: .25, 5: .35, 6: .15}
    distances = {d: round(target * weight, 1) for d, weight in weights.items()}
    distances[6] = round(max(0, target - sum(distances[d] for d in (1, 3, 5))), 1)
    sessions = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        km = distances.get(offset, 0)
        kind = "rest" if km == 0 else "intervals" if offset == 1 and scenario != "missed_session" and baseline >= 10 else "long" if offset == 5 else "easy"
        guide = guides.get(day.isoformat(), "pending")
        venue = "home" if kind == "rest" else "track" if guide == "accepted" else "treadmill"
        if kind == "rest":
            reason = "Recovery day. No workout is scheduled."
            summary = "Rest today. Take time to recover."
            guide = "not_required"
        elif guide == "accepted":
            reason = "A confirmed guide is available for this track session."
            summary = f"{kind.capitalize()} run: {km:g} kilometres on the track with your confirmed guide."
        else:
            reason = "Your guide cancelled; the session moves indoors." if guide == "declined" else "No guide is confirmed, so this session stays on the treadmill."
            summary = f"{kind.capitalize()} run: {km:g} kilometres on the treadmill. No guide is required."
        sessions.append(Session(id=stable_id(athlete_id, day), athlete_id=athlete_id, date=day, kind=kind, km=km,
                                venue=venue, guide_status=guide, spoken_summary=summary, rationale=reason))
    rationale = "A steady week based on your last three complete weeks. Outdoor sessions require a confirmed guide; other runs stay indoors."
    if scenario == "guide_cancelled":
        rationale = "Tuesday's guide cancelled. Keep the same distance and move that session to the treadmill; Saturday's confirmed session stays on track."
    elif scenario == "missed_session":
        rationale = "A missed session calls for a lighter week. Reduce planned distance by 20% and replace intervals with an easy run."
    if target == 0:
        rationale = "There is not enough recent running history to propose a training load. Add an athlete-authored training log before scheduling workouts."
    return Plan(id=stable_id(athlete_id, week_start), athlete_name=athlete_name, week_start=week_start,
                week_km=round(sum(s.km for s in sessions), 1), baseline_km=baseline,
                scenario=scenario, rationale=rationale, sessions=sessions)


def validate_plan(plan: Plan, history: list[Activity], guides: dict[str, str], *, athlete_id: str = "sara", athlete_name: str = "Sara") -> dict:
    baseline = baseline_km(history, plan.week_start)
    total = round(sum(s.km for s in plan.sessions), 2)
    dates = [s.date for s in plan.sessions]
    expected_dates = [plan.week_start + timedelta(days=i) for i in range(7)]
    checks = []

    def check(name: str, passed: bool, detail: str):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    check("Seven unique days", dates == expected_dates and plan.week_start.weekday() == 0,
          "One ordered session per day, Monday through Sunday.")
    check("Athlete identity", plan.athlete_name == athlete_name and plan.goal == "A comfortable, consistent 5K",
          "The proposal preserves the selected athlete and goal.")
    check("Volume cap", total <= baseline * 1.10 + .001 and abs(plan.baseline_km - baseline) < .01,
          f"{total:g} km planned; {baseline:g} km recent weekly average; cap is a prototype rule.")
    check("Distance accounting", abs(total - plan.week_km) < .01,
          "The displayed weekly total equals the sum of daily distances.")
    hard_dates = sorted(s.date for s in plan.sessions if s.kind in ("intervals", "long"))
    check("Recovery spacing", all((b - a).days > 1 for a, b in zip(hard_dates, hard_dates[1:])),
          "No consecutive interval or long-run days.")
    check("Rest day", any(s.kind == "rest" for s in plan.sessions), "At least one rest day each week.")
    check("Session consistency", all(
        (s.km == 0 and s.venue == "home") if s.kind == "rest" else (s.km > 0 and s.venue != "home")
        for s in plan.sessions), "Rest means zero kilometres; workouts need a running venue and positive distance.")
    check("Confirmed outdoor guide", all(
        s.venue not in ("track", "park") or
        (guides.get(s.date.isoformat()) == "accepted" and s.guide_status == "accepted")
        for s in plan.sessions), "Every outdoor run, including a track run, needs an independently confirmed guide.")
    check("Honest guide status", all(s.guide_status != "accepted" or guides.get(s.date.isoformat()) == "accepted"
                                    for s in plan.sessions), "Availability and pending invitations are not confirmations.")
    check("Speakable summaries", all(len(s.spoken_summary.split()) <= 25 for s in plan.sessions),
          "Each spoken session summary contains at most 25 words.")
    check("Stable action identities", plan.id == stable_id(athlete_id, plan.week_start) and all(
        s.id == stable_id(athlete_id, s.date) and s.athlete_id == athlete_id for s in plan.sessions),
        "Replanning reuses the same athlete/date event identifiers.")
    if plan.scenario == "missed_session":
        check("Missed-session adaptation", total <= baseline * .8 + .11 and all(s.kind != "intervals" for s in plan.sessions),
              "Missed-session scenario reduces volume by at least 20% with rounding tolerance and removes intervals.")
    return {"passed": all(c["passed"] for c in checks), "checks": checks}
