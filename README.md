# RunSense

RunSense is an accessible running-coach prototype for blind and low-vision
runners. It turns recent training history and guide availability into an
explainable seven-day plan, adapts that plan when circumstances change, and
reads key information aloud.

[View the timed two-minute demo](https://drive.google.com/drive/folders/1Mag989gHF5CjCyHXeaRw-CQGyMqW22q-?usp=sharing).

> RunSense is an assistive planning prototype. It does not replace a sighted
> guide, navigation aid, emergency service, clinician, or qualified coach.

## What is built

- A **Flutter client** with Home, Week Plan, Live Run, and Session Summary
  screens. It includes spoken coaching, large controls, light and dark themes,
  and a deterministic demo of GPS updates and obstacle alerts.
- A **FastAPI backend** that creates and persists seven-day plans, recalculates
  after a guide cancellation or missed session, and exposes the plan's
  validation evidence.
- Four explicit planning checks: weekly-volume cap, hard-day spacing, guide
  requirement for outdoor sessions, and concise spoken summaries.
- A bounded **LangChain/Claude coaching agent** that can use typed planning,
  Strava, and Calendar tools when credentials are configured.
- Live-session APIs for GPS samples, pause/resume/finish, aggregate persistence,
  TCX export, and owner-confirmed Strava upload.
- SQLAlchemy models and Alembic migrations for athletes, activities, plans,
  sessions, alerts, and tool traces. SQLite is the included local database;
  another SQLAlchemy database can be configured when its driver is installed.

```text
Flutter client
    -> FastAPI routes
    -> services and independently validated planning rules
    -> repositories -> SQLAlchemy -> SQLite
    -> optional provider clients -> Strava, Google Calendar, Claude, ElevenLabs
```

## External apps and services

| Integration                        | What RunSense uses it for                                                                                                                                                                          | Current evidence                       |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| Strava                             | Reads an athlete's profile and running history, normalizes activity summaries without GPS coordinates, verifies completed runs, and uploads a finished TCX only after explicit owner confirmation. | The real HTTP adapter is implemented.  |
| Google Calendar                    | Creates or updates deterministic workout events, reads them back, and checks a guide's RSVP. Every write requires explicit confirmation and is reconciled to avoid duplicates.                     | The real HTTP adapter is implemented.  |
| Anthropic Claude through LangChain | Selects from typed planning, Strava, and Calendar tools for the coach chat. The deterministic plan endpoint does not require Claude.                                                               | The agent loop is tested successfully. |
| ElevenLabs                         | Optionally produces a more natural Flutter voice. If it is unavailable, the client falls back to on-device/browser text to speech.                                                                 | Tested and running successfully.       |

Provider-backed `/v1/*` routes can be protected with `RUNSENSE_API_KEY`.
Strava uploads and Calendar writes are never implicit. Configuration examples
are in [.env.example](.env.example); the file is a reference and is not loaded
automatically by the Python application.

## Run the backend

Requirements: Python 3.11 or newer.

From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open the [local API documentation](http://127.0.0.1:8000/api/docs) or
check [the local health endpoint](http://127.0.0.1:8000/health). No external
credentials are needed to call `POST /api/plan` or run the automated tests.
Local startup creates missing SQLite tables automatically.

To manage the schema explicitly:

```sh
.venv/bin/alembic upgrade head
```

Docker is also supported:

```sh
cp .env.example .env
docker compose up --build
```

## Run the Flutter app

Requirements: a Flutter SDK compatible with Dart `^3.13.3` and an Android
emulator. Start the backend first, then run:

```sh
cd Application
flutter pub get
flutter run
```

The checked-in client URL is `http://10.0.2.2:8000`, Android Emulator's alias
for the development computer. For a physical device or Flutter web, update
`Application/lib/services/api_config.dart` to an address that the device or
browser can reach. Keep the backend on a trusted network when binding it beyond
localhost.

ElevenLabs is optional. To enable it, copy `Application/env.example.json` to
the gitignored `Application/env.json`, insert a valid key, and run:

```sh
flutter run --dart-define-from-file=env.json
```

Without that file, RunSense uses the platform's text-to-speech voice.

## Configure live integrations

Export only the providers you intend to use in the shell that starts Uvicorn:

```sh
export RUNSENSE_API_KEY="choose-a-strong-local-token"
export STRAVA_ACCESS_TOKEN="..."
export GOOGLE_CALENDAR_ACCESS_TOKEN="..."
export GOOGLE_CALENDAR_ID="primary"
export ANTHROPIC_API_KEY="..."
export ANTHROPIC_MODEL="..."
```

Do not commit tokens. If `RUNSENSE_API_KEY` is set, clients calling `/v1/*`
must send `Authorization: Bearer <token>`. The Flutter agent-chat client does
not yet send that header, so either leave the API key unset for an isolated
local demo or add authenticated client configuration before exposing the
backend.

## How it was tested

Run the backend checks from the repository root:

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app migrations
```

The current backend suite passes **22 tests**. It covers plan generation and
persistence, all four planning rules, authenticated provider routes, Strava
normalization, session lifecycle and TCX export, Calendar confirmation, and
the LangChain tool loop.

Run the Flutter checks from `Application/`:

```sh
flutter analyze
flutter test
```

The Flutter project contains two widget tests for the Home screen and the full
deterministic Start Session -> spoken alert sequence -> End Session -> summary
flow. They also query semantic labels for the live and summary alert counts.

In addition to that, the app was tested in the home against real obstacles (e.g. a chair, and other house goods) and the testing was successful.

## Accessibility

- Controls use text labels and semantic descriptions rather than relying on
  icons or colour alone.
- The interface supports the system light/dark theme and uses large primary
  touch targets.
- Important plans, alerts, and session results can be spoken; new speech
  interrupts stale cues so urgent information is not queued behind it.
- The demo walkthrough includes the exact spoken script as a transcript. The
  published video should include accurate captions and visible focus states.
- Automated semantics checks supplement, but do not replace, testing with
  blind and low-vision runners using TalkBack or VoiceOver.

## More documentation

- [Two-minute demo script and transcript](https://drive.google.com/drive/folders/1Mag989gHF5CjCyHXeaRw-CQGyMqW22q-?usp=sharing)
