"""Executable scenario evidence, deliberately excluding unmeasured perception metrics.

The ``perception`` key reports only the deterministic triage-logic fixtures from
``perception_eval``. It is a sibling of the scenario tally on purpose: synthetic
detection sequences are not agent scenarios, and neither one is a measurement of
real-world computer vision.
"""
import tempfile
from datetime import date, timedelta

from .agent import Agent
from .models import Activity, PlanRequest
from .perception_eval import evaluate_perception
from .planner import demo_history, generate_plan, guide_confirmations, validate_plan
from .store import Store


async def evaluate() -> dict:
    week = date(2026, 9, 14)
    results = []

    def record(name, passed, detail):
        results.append({"name": name, "passed": bool(passed), "detail": detail})

    # Different loads and guide constraints exercise the production planning path.
    for name, load, guide_days in [
        ("No history", 0, []), ("New runner", 3, []), ("Low volume", 8, [5]),
        ("Regular runner", 19, [1, 5]), ("Higher volume", 40, [1, 5]),
        ("Weekend guide only", 19, [5]), ("Treadmill only", 19, []),
        ("Tuesday guide only", 19, [1]), ("Sparse history", 2, [1, 5]),
        ("No guide confirmed", 25, []),
    ]:
        history = [Activity(date=week - timedelta(weeks=w), km=load, source="synthetic") for w in (1, 2, 3)]
        guides = {(week + timedelta(days=d)).isoformat(): "accepted" for d in guide_days}
        plan = generate_plan(history, week, guides=guides)
        record(name, validate_plan(plan, history, guides)["passed"], f"Synthetic profile; {load} km weekly baseline.")

    with tempfile.TemporaryDirectory(prefix="runsense-eval-") as directory:
        store = Store(f"{directory}/eval.sqlite3")
        agent = Agent(store)
        initial = await agent.plan(PlanRequest(week_start=week))
        repeated = await agent.plan(PlanRequest(week_start=week))
        record("Repeat plan without duplicates", store.count_actions("demo_calendar") == 4 and
               {e["id"] for e in initial["calendar_events"]} == {e["id"] for e in repeated["calendar_events"]},
               "Two complete runs leave four simulated calendar events and one journal page.")
        cancelled = await agent.plan(PlanRequest(week_start=week, scenario="guide_cancelled"))
        tuesday = cancelled["plan"]["sessions"][1]
        record("Cancelled guide adaptation", tuesday["venue"] == "treadmill" and tuesday["guide_status"] == "declined" and
               store.count_actions("demo_calendar") == 4, "Cancelled Tuesday guide moves the existing session indoors.")
        missed = await agent.plan(PlanRequest(week_start=week, scenario="missed_session"))
        record("Missed-session adaptation", missed["plan"]["week_km"] < initial["plan"]["week_km"] and
               all(s["kind"] != "intervals" for s in missed["plan"]["sessions"]), "Reduced volume and removed intervals.")
        retry = await agent.plan(PlanRequest(week_start=week, scenario="calendar_retry"))
        record("Injected failure recovery", any(t["status"] == "retrying" for t in retry["trace"]) and
               store.count_actions("demo_calendar") == 4, "Simulated pre-write 503 is retried once; no duplicate events.")

    history = demo_history(week)
    guides = guide_confirmations(week, "baseline")
    invalid = generate_plan(history, week, guides=guides)
    invalid.sessions[3].venue = "track"
    invalid.sessions[3].guide_status = "accepted"
    record("Reject invented guide confirmation", not validate_plan(invalid, history, guides)["passed"],
           "A claimed acceptance without independent confirmation is rejected, including at a track.")
    invalid = generate_plan(history, week, guides=guides)
    invalid.sessions[1].km = 100
    invalid.week_km = sum(s.km for s in invalid.sessions)
    record("Reject excess volume", not validate_plan(invalid, history, guides)["passed"], "A proposal above the configured cap is blocked.")
    return {"passed": sum(r["passed"] for r in results), "total": len(results), "results": results,
            "scope": "Deterministic synthetic scenarios, local persistence and failure injection; not live API or clinical validation.",
            "perception": evaluate_perception()}


if __name__ == "__main__":
    import asyncio
    import json
    report = asyncio.run(evaluate())
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] == report["total"] else 1)

