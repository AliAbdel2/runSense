# RunSense

RunSense is an accessible running-coach prototype with a Flutter client and a
FastAPI backend. The backend follows the current `main` architecture:

```text
routes → services → repositories → SQLAlchemy models → SQLite/Postgres
             ↘ provider clients (Strava, Google Calendar, LangChain)
```

## Run locally

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [the API docs](http://127.0.0.1:8000/api/docs). Configure
`RUNSENSE_API_KEY` to protect provider-backed `/v1` routes with Bearer auth.
The Flutter client lives in `Application/` and currently uses its mock service
implementations for the demo.

## Integrated features

- `POST /api/plan` creates a deterministic seven-day plan and persists its
  `plan_weeks` and `sessions` rows. Guide cancellation moves Tuesday indoors;
  missed-session planning reduces volume and removes intervals.
- `/v1/strava/*` provides typed Strava athlete, activity, training-history,
  laps, streams, zones, and completed-run matching operations. Normalized
  activity summaries are persisted in `activities`; raw provider payloads and
  GPS coordinates are not.
- `/v1/calendar/*` provides explicitly confirmed, idempotent Calendar event
  creation, read-back, and guide RSVP checks.
- `/v1/sessions/*` tracks live GPS metrics in memory, persists aggregate
  session state, exports TCX, and supports explicitly confirmed Strava upload.

## Database

The SQLAlchemy models are in `app/models/`, repositories in
`app/repositories/`, and the initial schema is in
`migrations/versions/0001_initial.py`. For a managed database run:

```sh
.venv/bin/alembic upgrade head
```

Local development also bootstraps missing tables on application startup. Do
not commit credentials; use `.env.example` as the configuration reference.

## Verification

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app migrations
```
