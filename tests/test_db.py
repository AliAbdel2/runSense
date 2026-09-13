from datetime import date, datetime

from sqlalchemy import inspect

from runsense.db import (Activity, Alert, Athlete, PlanWeek, Session, ToolTrace, TypedStore, get_session_factory,
                         init_engine, list_alerts, list_tool_traces, record_alert, record_tool_trace)


def factory(tmp_path):
    return get_session_factory(str(tmp_path / "typed.sqlite3"))


def test_init_engine_creates_all_typed_tables(tmp_path):
    engine = init_engine(str(tmp_path / "typed.sqlite3"))
    tables = set(inspect(engine).get_table_names())
    assert {"athletes", "activities", "plan_weeks", "sessions", "alerts", "tool_traces"} <= tables


def test_init_engine_uses_runsense_db_env_var(tmp_path, monkeypatch):
    path = tmp_path / "from-env.sqlite3"
    monkeypatch.setenv("RUNSENSE_DB", str(path))
    init_engine()
    assert path.exists()


def test_athlete_round_trip(tmp_path):
    with factory(tmp_path)() as session:
        session.add(Athlete(id="sara", name="Sara", guide_contacts=[{"name": "Ade"}],
                            preferences={"venue": "track"}))
        session.commit()
        stored = session.get(Athlete, "sara")
        assert (stored.name, stored.strava_token, stored.calendar_token) == ("Sara", None, None)
        assert stored.guide_contacts == [{"name": "Ade"}]
        assert stored.preferences == {"venue": "track"}


def test_activity_round_trip(tmp_path):
    with factory(tmp_path)() as session:
        session.add(Athlete(id="sara", name="Sara"))
        session.add(Activity(id="a1", athlete_id="sara", strava_id="99", date=date(2026, 9, 7),
                             km=5.2, avg_pace="6:10", avg_hr=142, elevation=18.5))
        session.commit()
        stored = session.get(Activity, "a1")
        assert (stored.athlete_id, stored.strava_id, stored.date) == ("sara", "99", date(2026, 9, 7))
        assert (stored.km, stored.avg_pace, stored.avg_hr, stored.elevation) == (5.2, "6:10", 142, 18.5)


def test_plan_week_round_trip_with_serialized_plan(tmp_path):
    plan_json = {"id": "plan-1", "week_start": "2026-09-07", "sessions": [{"id": "s1"}]}
    with factory(tmp_path)() as session:
        session.add(Athlete(id="sara", name="Sara"))
        session.add(PlanWeek(id="pw1", athlete_id="sara", week_start=date(2026, 9, 7),
                             plan_json=plan_json, rationale="Keep the long run indoors."))
        session.commit()
        stored = session.get(PlanWeek, "pw1")
        assert stored.plan_json == plan_json
        assert (stored.week_start, stored.rationale, stored.version) == (date(2026, 9, 7),
                                                                        "Keep the long run indoors.", 1)


def test_session_round_trip(tmp_path):
    with factory(tmp_path)() as session:
        session.add(Athlete(id="sara", name="Sara"))
        session.add(PlanWeek(id="pw1", athlete_id="sara", week_start=date(2026, 9, 7)))
        session.add(Session(id="s1", plan_week_id="pw1", calendar_event_id="evt-1", guide_status="accepted",
                            started_at=datetime(2026, 9, 8, 6, 30), ended_at=datetime(2026, 9, 8, 7, 5),
                            summary_json={"km": 5.0}))
        session.commit()
        stored = session.get(Session, "s1")
        assert (stored.plan_week_id, stored.calendar_event_id, stored.guide_status) == ("pw1", "evt-1", "accepted")
        assert stored.started_at == datetime(2026, 9, 8, 6, 30)
        assert stored.ended_at == datetime(2026, 9, 8, 7, 5)
        assert stored.summary_json == {"km": 5.0}


def test_session_defaults_are_nullable(tmp_path):
    with factory(tmp_path)() as session:
        session.add(Athlete(id="sara", name="Sara"))
        session.add(PlanWeek(id="pw1", athlete_id="sara", week_start=date(2026, 9, 7)))
        row = Session(plan_week_id="pw1")
        session.add(row)
        session.commit()
        assert row.id and row.guide_status == "not_required"
        assert (row.calendar_event_id, row.started_at, row.ended_at, row.summary_json) == (None, None, None, None)


def test_record_alert_and_list_alerts(tmp_path):
    with factory(tmp_path)() as session:
        session.add(Athlete(id="sara", name="Sara"))
        session.add(PlanWeek(id="pw1", athlete_id="sara", week_start=date(2026, 9, 7)))
        session.add(Session(id="s1", plan_week_id="pw1"))
        session.commit()
        alert = record_alert(session, obj_class="person", zone="left", distance_bucket="near",
                             tier="urgent", session_id="s1", latency_ms=180.5, spoken=True)
        loose = record_alert(session, obj_class="pole", zone="center", distance_bucket="far", tier="advisory")
        assert alert.id and alert.id != loose.id
        assert isinstance(alert.ts, datetime)
        assert loose.session_id is None and loose.spoken is False and loose.latency_ms is None

        for_session = list_alerts(session, "s1")
        assert [a.id for a in for_session] == [alert.id]
        assert for_session[0].obj_class == "person"
        assert for_session[0].zone == "left"
        assert for_session[0].distance_bucket == "near"
        assert for_session[0].tier == "urgent"
        assert for_session[0].latency_ms == 180.5
        assert for_session[0].spoken is True
        assert {a.id for a in list_alerts(session)} == {alert.id, loose.id}


def test_record_tool_trace_and_list_tool_traces(tmp_path):
    with factory(tmp_path)() as session:
        trace = record_tool_trace(session, tool="calendar.upsert_session", step=2, run_id="run-1",
                                  input_json={"session_id": "s1"}, output_json={"status": "created"},
                                  latency_ms=42.0, retries=1, error=None)
        other = record_tool_trace(session, tool="plan.generate")
        assert trace.id and trace.id != other.id
        assert isinstance(trace.created_at, datetime)
        assert (other.step, other.run_id, other.retries) == (0, None, 0)
        assert (other.input_json, other.output_json, other.error) == ({}, {}, None)

        stored = session.get(ToolTrace, trace.id)
        assert (stored.tool, stored.step, stored.run_id) == ("calendar.upsert_session", 2, "run-1")
        assert stored.input_json == {"session_id": "s1"}
        assert stored.output_json == {"status": "created"}
        assert (stored.latency_ms, stored.retries) == (42.0, 1)
        assert [t.id for t in list_tool_traces(session, "run-1")] == [trace.id]
        assert len(list_tool_traces(session)) == 2


def test_typed_store_helpers_without_session_boilerplate(tmp_path):
    store = TypedStore(str(tmp_path / "typed.sqlite3"))
    athlete = store.get_or_create_athlete("sara", name="Sara", preferences={"venue": "park"})
    again = store.get_or_create_athlete("sara", name="Ignored")
    assert again.id == athlete.id and again.name == "Sara"

    alert = store.record_alert(obj_class="dog", zone="right", distance_bucket="mid", tier="advisory")
    assert [a.id for a in store.list_alerts()] == [alert.id]
    trace = store.record_tool_trace(tool="voice.speak", run_id="run-9")
    assert [t.id for t in store.list_tool_traces("run-9")] == [trace.id]

    store.add(Activity(id="a1", athlete_id="sara", date=date(2026, 9, 7), km=4.0))
    assert store.get(Activity, "a1").km == 4.0


def test_typed_tables_coexist_with_blob_store_in_one_file(tmp_path):
    from runsense.store import Store

    path = str(tmp_path / "shared.sqlite3")
    blob = Store(path)
    blob.save_run({"run_id": "run-1", "mode": "demo"})
    store = TypedStore(path)
    store.record_tool_trace(tool="plan.generate", run_id="run-1")
    assert blob.get_run("run-1") == {"run_id": "run-1", "mode": "demo"}
    assert [t.run_id for t in store.list_tool_traces("run-1")] == ["run-1"]
