# RunSense

RunSense is an accessible running coach for blind and low-vision runners. It
combines a Flutter mobile app with a FastAPI backend to create training plans,
brief the runner by voice, track a live run, warn about obstacles, and save the
completed session.

## Two-minute demo

[Watch the two-minute demo](DEMO_URL_HERE)

Replace `DEMO_URL_HERE` with the published YouTube, Loom, or Google Drive URL
before submission.

## What is built

### Flutter app

- Accessible home, weekly-plan, coach-briefing, live-run, and session-summary
  screens with large controls, semantic labels, and spoken feedback.
- Real backend clients for plan generation, Claude coach chat, live-session
  start/finish, and GPS sample uploads.
- Real device GPS tracking for distance and pace, including pace coaching.
- On-device camera obstacle detection with Google ML Kit, directional warnings,
  urgency levels, vibration, and spoken alerts. Web builds safely fall back to
  mock perception because the camera pipeline targets Android/iOS.
- ElevenLabs cloud speech with device text-to-speech as an offline fallback.
- Mock services retained only for deterministic widget tests through the
  `RunSenseApp(forceMocks: true)` test seam.

### FastAPI backend

- Deterministic seven-day plan generation with volume, hard-day-spacing,
  guide, and spoken-summary validation before persistence.
- Claude tool-use coach over planning, Strava, and Google Calendar operations.
- Live-session lifecycle endpoints for GPS samples, pause/resume, aggregate
  distance and pace, TCX export, and confirmed Strava upload.
- Typed provider clients, SQLAlchemy repositories, SQLite/Postgres support,
  Alembic migrations, bearer protection for `/v1/*`, and generated API docs.

The hosted API is available at
[runsense-x658.onrender.com](https://runsense-x658.onrender.com/), with
[health](https://runsense-x658.onrender.com/health) and
[API documentation](https://runsense-x658.onrender.com/api/docs).

## External connections

| Service | Purpose | Current status |
| --- | --- | --- |
| Anthropic Claude | Coach conversation and tool selection | Connected on the Render backend |
| Google Calendar | Create, verify, and check guide status for training events | Connected on the Render backend |
| ElevenLabs | Natural spoken coaching and safety alerts | Connected from the Flutter app when `env.json` is supplied |
| Strava | Athlete/activity reads, run matching, and confirmed TCX upload | Integration built; credentials are not currently configured on Render |

Google ML Kit performs obstacle inference locally on the phone; camera frames
and GPS coordinates are not stored as raw provider data by the backend.

## Run the app

### Hosted backend

Requirements: Flutter, an Android emulator or phone, and valid local
credentials. From the repository root:

```sh
cd Application
cp env.example.json env.json
```

Set `RUNSENSE_API_KEY` in `env.json` to the same value configured on Render,
then run:

```sh
flutter pub get
flutter run --dart-define-from-file=env.json
```

`env.json` is ignored by Git. The checked-in example already points to the
Render backend. A full restart is required after changing Dart defines; hot
reload does not replace them.

### Local backend

Create `.env` from `.env.example`, add the provider credentials you need, and
start the container:

```sh
cp .env.example .env
docker compose up --build
```

For an Android emulator, set `RUNSENSE_API_BASE_URL` in `Application/env.json`
to `http://10.0.2.2:8000`. The API docs are then available at
`http://127.0.0.1:8000/api/docs` on the host.

## Testing

Backend verification:

```sh
python -m pytest -q
python -m compileall -q app migrations
```

The current backend run passes **22 tests** covering plan validation and
persistence, authenticated routes, live GPS-session recording and TCX export,
agent behavior, Calendar safety gates, and Strava normalization.

Flutter verification commands:

```sh
cd Application
flutter analyze
flutter test
flutter build apk --debug
```

The obstacle pipeline was previously exercised on an Android emulator and the
Flutter test suite uses forced mocks for repeatability. After the latest live
backend/GPS wiring, backend tests pass, but Flutter analysis/tests still need to
be rerun on a machine with the Flutter SDK installed.

## Repository layout

```text
app/          FastAPI routes, services, repositories, and models
Application/ Flutter mobile client
migrations/  Alembic database migrations
tests/       Backend test suite
dashboard/   Read-only Streamlit database viewer
```
