import asyncio
import json
import os
from datetime import date
from time import perf_counter
from uuid import uuid4

from .models import Activity, Plan, PlanRequest
from .observability import record_run_trace
from .planner import demo_history, generate_plan, guide_confirmations, next_monday, stable_id, validate_plan
from .store import Store
from .strava_source import StravaSource, StravaSourceError


class Agent:
    def __init__(self, store: Store, strava_source: StravaSource | None = None):
        self.store = store
        self.commit_lock = asyncio.Lock()
        self.strava = strava_source or StravaSource()

    async def plan(self, request: PlanRequest, live: bool = False) -> dict:
        if request.source == "strava_mcp":
            async with self.commit_lock:
                return await self._strava_plan(request)
        if live:
            async with self.commit_lock:
                return await self._plan(request, live=True)
        return await self._plan(request)

    async def _strava_plan(self, request: PlanRequest) -> dict:
        if request.scenario != "baseline":
            raise StravaSourceError("Synthetic scenarios cannot modify personal Strava data. Use the demo scenario controls separately.")
        week = request.week_start or next_monday()
        if week.weekday() != 0:
            raise StravaSourceError("week_start must be a Monday.")
        trace = []
        history = await self.strava.get_activities(week, trace)
        guides = {}  # No inferred guide confirmations from an activity log.
        profile = {"athlete_id": "strava-personal", "athlete_name": "You"}
        if request.use_llm:
            from .llm import propose_with_claude
            plan = await propose_with_claude(history, week, "baseline", guides, trace, **profile)
        else:
            plan = generate_plan(history, week, "baseline", guides, **profile)
        validation = validate_plan(plan, history, guides, **profile)
        if not validation["passed"]:
            raise StravaSourceError("Personal plan failed validation. No external actions were taken.")
        trace.append({"tool": "plan.validate", "status": "completed", "attempt": 1, "latency_ms": 0,
                      "detail": "Personal plan passed independent rules. No guide acceptance was inferred."})
        trace.append({"tool": "preview.prepare", "status": "completed", "attempt": 1, "latency_ms": 0,
                      "detail": "Personal preview only. No SQLite history, Calendar events or Notion pages were written."})
        result = {"run_id": uuid4().hex, "mode": "strava_preview", "source": "strava_mcp",
                  "planner": "claude" if request.use_llm else "deterministic",
                  "plan": plan.model_dump(mode="json"), "validation": validation, "trace": trace,
                  "calendar_events": [], "audio_url": None, "committed": False,
                  "retention": "memory_only", "expires_in_seconds": self.strava.ttl_seconds}
        # Raw MCP results and normalized history leave scope without persistence.
        # The trace is deliberately not mirrored into the typed tool_traces table
        # either: a personal Strava preview is memory-only with a TTL, and a
        # queryable copy of its steps would outlive that promise.
        self.strava.save_preview(result)
        return result

    async def _plan(self, request: PlanRequest, live: bool = False) -> dict:
        week = request.week_start or next_monday()
        if week.weekday() != 0:
            raise ValueError("week_start must be a Monday.")
        if live and request.scenario != "baseline":
            raise ValueError("Injected scenarios are demo-only. Live guide changes require provider confirmation.")
        run_id = uuid4().hex
        trace = []
        started = perf_counter()
        if live:
            from .integrations import Settings, SheetsClient
            async with SheetsClient(Settings.from_env()) as client:
                history = [Activity.model_validate(a) for a in await client.get_activities()]
            guides = guide_confirmations(week, request.scenario, demo=False)
            # Live guide invitation/RSVP workflow is deferred. Fail closed to indoor sessions.
        else:
            history = demo_history(week)
            guides = guide_confirmations(week, request.scenario)
        trace.append({"tool": "sheets.read_training_log", "status": "completed", "attempt": 1,
                      "latency_ms": round((perf_counter() - started) * 1000, 2),
                      "detail": f"Read {len(history)} {'athlete-authored rows from Google Sheets' if live else 'synthetic fixture rows; no Google Sheets request'}."})
        started = perf_counter()
        if request.use_llm:
            from .llm import propose_with_claude
            plan = await propose_with_claude(history, week, request.scenario, guides, trace)
        else:
            plan = generate_plan(history, week, request.scenario, guides)
        trace.append({"tool": "plan.generate", "status": "completed", "attempt": 1,
                      "latency_ms": round((perf_counter() - started) * 1000, 2),
                      "detail": "Claude tool-use proposal." if request.use_llm else "Deterministic planning rules; no model call."})
        validation = validate_plan(plan, history, guides)
        if not validation["passed"]:
            raise ValueError("Plan failed validation; no external actions were taken.")
        trace.append({"tool": "plan.validate", "status": "completed", "attempt": 1, "latency_ms": 0,
                      "detail": f"All {len(validation['checks'])} planning checks passed."})
        result = {"run_id": run_id, "mode": "live_preview" if live else "demo",
                  "planner": "claude" if request.use_llm else "deterministic", "plan": plan.model_dump(mode="json"),
                  "validation": validation, "trace": trace, "calendar_events": [], "audio_url": None,
                  "history": [a.model_dump(mode="json") for a in history], "guides": guides, "committed": False}
        if not live:
            self.simulate_actions(result, inject_failure=request.scenario == "calendar_retry")
        if request.scenario == "guide_cancelled":
            await self.notify_guide_change(result)
        self.store.save_run(result)
        # Second, queryable copy of the same trace steps. The in-memory list and the
        # blob run payload above are unchanged; this is additive and never fatal.
        record_run_trace(result, self.store.path)
        if live:
            self.store.upsert_action("latest_live_preview", plan.id, {"run_id": run_id})
        return self.public(result)

    @staticmethod
    def public(result: dict) -> dict:
        return {k: v for k, v in result.items() if k not in ("history", "guides")}

    def simulate_actions(self, result: dict, inject_failure: bool = False):
        trace = result["trace"]
        for index, session in enumerate(s for s in result["plan"]["sessions"] if s["kind"] != "rest"):
            started = perf_counter()
            attempt = 1
            if inject_failure and index == 0:
                trace.append({"tool": "calendar.upsert_session", "status": "retrying", "attempt": 1,
                              "latency_ms": 0, "detail": "Injected simulated 503 before write; retrying once."})
                attempt = 2
            action = self.store.upsert_action("demo_calendar", session["id"], {"session": session})
            result["calendar_events"].append({"id": action["id"], "status": action["status"]})
            trace.append({"tool": "calendar.upsert_session", "status": "completed", "attempt": attempt,
                          "latency_ms": round((perf_counter() - started) * 1000, 2),
                          "detail": f"Simulated event {action['status']} for {session['date']}; stable ID {session['id'][:8]}."})
            if self.store.get_action("demo_calendar", session["id"])["session"] != session:
                raise ValueError("Simulated event read-back mismatch.")
        trace.append({"tool": "calendar.verify", "status": "completed", "attempt": 1, "latency_ms": 0,
                      "detail": f"Read back {len(result['calendar_events'])} local simulated events and compared their contents."})
        self.store.upsert_action("demo_notion", result["plan"]["id"], {"plan": result["plan"]})
        trace.append({"tool": "notion.upsert_plan", "status": "completed", "attempt": 1, "latency_ms": 0,
                      "detail": "Plan and adaptation rationale saved to the local simulated journal."})
        trace.append({"tool": "voice.prepare_summary", "status": "completed", "attempt": 1, "latency_ms": 0,
                      "detail": "Speakable summaries ready. Browser speech runs only when Listen is pressed; ElevenLabs was not called."})

    async def notify_guide_change(self, result: dict) -> str:
        """Best-effort SMS when a cancelled guide moves a session indoors.

        Optional and never fatal: an unset contact, missing Twilio credentials or
        a failed send all record an honest trace note and the adaptation still
        completes.  A message is only ever sent when someone has deliberately set
        both RUNSENSE_GUIDE_PHONE and Twilio credentials, so the demo scenarios
        stay side-effect free by default.
        """
        from .delivery import SMS_NOT_CONFIGURED, send_sms_notice

        moved = [s for s in result["plan"]["sessions"] if s["guide_status"] == "declined"]
        contact = os.getenv("RUNSENSE_GUIDE_PHONE", "").strip()
        started = perf_counter()
        if not contact or not moved:
            status = SMS_NOT_CONFIGURED
        else:
            dates = ", ".join(s["date"] for s in moved)
            text = (f"RunSense: your guide cancelled for {dates}. That session keeps the same distance "
                    "and moves to the treadmill. Reply to your guide to reschedule.")
            try:
                status = await send_sms_notice(contact, text)
            except Exception:
                # send_sms_notice is already non-raising; this is a last resort so
                # an unexpected transport failure cannot void a valid adaptation.
                status = "sms_failed"
        sent = status not in (SMS_NOT_CONFIGURED, "sms_failed", "sms_invalid_request")
        details = {
            SMS_NOT_CONFIGURED: "No SMS sent: set RUNSENSE_GUIDE_PHONE and Twilio credentials to notify the athlete's guide contact.",
            "sms_failed": "SMS provider rejected the reschedule notice. The indoor adaptation still stands; notify the guide manually.",
            "sms_invalid_request": "SMS not attempted: the configured guide contact or message was empty.",
        }
        result["trace"].append({
            "tool": "sms.notify_guide_change", "status": "completed" if sent else "skipped",
            "attempt": 1, "latency_ms": round((perf_counter() - started) * 1000, 2),
            "detail": details.get(status, f"Reschedule notice sent to the configured guide contact; provider status {status}."),
        })
        return status

    async def commit(self, run_id: str) -> dict:
        from .integrations import CalendarClient, NotionClient, Settings, SheetsClient
        async with self.commit_lock:
            if self.strava.get_preview(run_id):
                raise StravaSourceError("Strava personal previews cannot be exported by this prototype. Use the separate athlete-authored workflow for Calendar and Notion writes.")
            result = self.store.get_run(run_id)
            if not result or result["mode"] != "live_preview":
                raise ValueError("A saved live preview is required; demo runs cannot be committed.")
            if result.get("committed"):
                return self.public(result)
            plan = Plan.model_validate(result["plan"])
            latest = self.store.get_action("latest_live_preview", plan.id)
            if not latest or latest["run_id"] != run_id:
                raise ValueError("This preview was superseded. Review and commit the newest preview for this week.")
            validation = validate_plan(plan, [Activity.model_validate(a) for a in result["history"]], result["guides"])
            if not validation["passed"]:
                raise ValueError("Stored preview failed revalidation.")
            settings = Settings.from_env()
            # Check required credentials before any write, avoiding a known partial commit.
            if not settings.google_access_token or not settings.notion_api_key or not settings.notion_data_source_id:
                raise ValueError("Configure Calendar and Notion credentials before committing a preview.")
            if any(s.kind == "rest" and self.store.get_action("live_calendar", s.id) for s in plan.sessions):
                raise ValueError("A previously scheduled workout now becomes rest. Calendar cancellation support is pending; reconcile that event before committing.")
            async with SheetsClient(settings) as sheets:
                current_history = [Activity.model_validate(a).model_dump(mode="json") for a in await sheets.get_activities()]
            normalize = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
            if normalize(current_history) != normalize(result["history"]):
                raise ValueError("The training log changed after this preview. Generate and review a fresh plan before committing.")
            try:
                async with CalendarClient(settings) as calendar:
                    for session in plan.sessions:
                        if session.kind == "rest":
                            continue
                        started = perf_counter()
                        event = await calendar.upsert_session(session.model_dump(mode="json"))
                        if event.get("id") != session.id:
                            raise ValueError("Calendar returned an unexpected event identity.")
                        verified = await calendar.get_session(event["id"])
                        if verified.get("id") != event["id"] or verified.get("status") == "cancelled" or any(
                            verified.get(key) != event.get(key) for key in ("summary", "description", "location", "start", "end", "extendedProperties")
                        ):
                            raise ValueError("Calendar read-back did not match the written session.")
                        self.store.upsert_action("live_calendar", session.id, {"event_id": event["id"], "date": session.date.isoformat()})
                        result["trace"].append({"tool": "calendar.write_and_verify", "status": "completed", "attempt": 1,
                                               "latency_ms": round((perf_counter() - started) * 1000, 2),
                                               "detail": f"Calendar event for {session.date} written and read back; no invitations sent."})
                        result["calendar_events"] = [e for e in result["calendar_events"] if e["session_id"] != session.id]
                        result["calendar_events"].append({"id": event["id"], "session_id": session.id, "status": "verified"})
                        self.store.save_run(result)
                async with NotionClient(settings) as notion:
                    page = await notion.upsert_plan(plan.model_dump(mode="json"))
                    verified_page = await notion.get_plan(page["id"])
                    expected_properties = page.get("properties", {})
                    actual_properties = verified_page.get("properties", {})
                    def plain(prop, kind):
                        return "".join(item.get("plain_text", item.get("text", {}).get("content", "")) for item in prop.get(kind, []))
                    if (verified_page.get("id") != page["id"] or verified_page.get("archived") or
                        plain(actual_properties.get(settings.notion_plan_id_property, {}), "rich_text") != plan.id or
                        any(plain(actual_properties.get(prop, {}), kind) != plain(expected_properties.get(prop, {}), kind)
                            for prop, kind in [(settings.notion_title_property, "title"), (settings.notion_summary_property, "rich_text")]) or
                        plan.rationale not in plain(actual_properties.get(settings.notion_summary_property, {}), "rich_text")):
                        raise ValueError("Notion read-back did not match the saved plan.")
                self.store.upsert_action("live_notion", plan.id, {"page_id": page["id"]})
                result["trace"].append({"tool": "notion.upsert_plan", "status": "completed", "attempt": 1,
                                       "latency_ms": 0, "detail": "Notion plan identity, title and summary verified by read-back. Cross-app writes are not atomic."})
                result["committed"] = True
                self.store.save_run(result)
                record_run_trace(result, self.store.path)
                return self.public(result)
            except Exception:
                result["trace"].append({"tool": "workflow.commit", "status": "failed", "attempt": 1,
                                       "latency_ms": 0, "detail": "Commit stopped. Earlier verified writes may remain; retry this same run to reconcile."})
                self.store.save_run(result)
                # A stopped commit is exactly when the queryable trace matters most,
                # so it is recorded before the error propagates - best effort, as ever.
                record_run_trace(result, self.store.path)
                raise
