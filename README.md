# RunSense

A guide-aware training coordination prototype for blind and low-vision runners. Plan a week, inspect why a session was chosen, hear it aloud, and replay a guide cancellation or missed-session scenario.

**Current state:** a working local demo with synthetic data, a deterministic planner, durable traces and simulated Calendar/Notion actions. The official Strava MCP client now supports authenticated tool discovery and personal activity-based previews. An optional Claude tool loop, now on LangChain, and real HTTP adapters for Sheets, Calendar, Notion, ElevenLabs and Twilio are implemented and tested with mock transports. Obstacle-triage decision logic, a cross-run trace/alert view and a mobile app scaffold have been added, each with the narrow evidence described below and no more. No external accounts are connected or live-verified. This is not yet an eligible three-connected-app hackathon submission.

## Run locally

Python 3.11 or newer. From this directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m uvicorn runsense.main:app --host 127.0.0.1 --port 8000
```

Open [the dashboard](http://127.0.0.1:8000) or [API docs](http://127.0.0.1:8000/api/docs). No credentials are needed. Keep the server bound to localhost, with one worker.

The dashboard is responsive in a mobile browser. To test it from a phone on the
same Wi-Fi network, export `RUNSENSE_ALLOWED_HOSTS` with the computer's LAN IP
and bind the server to all local interfaces, then open that IP from the phone:

```sh
export RUNSENSE_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.23
.venv/bin/python -m uvicorn runsense.main:app --host 0.0.0.0 --port 8000
```

Replace `192.168.1.23` with the computer's actual LAN address. This is a
browser-accessible local app, not an offline or native phone application; the
computer running RunSense must stay on and reachable.

1. **Plan my week** generates Sara's next Monday–Sunday plan using a 19 km recent weekly baseline.
2. **Guide cancelled** moves Tuesday to the treadmill, retaining the same event identity.
3. **Missed session** reduces weekly distance by 20% and replaces intervals with easy running.
4. **Simulate Calendar failure** records a simulated pre-write 503, followed by a successful retry.
5. **Run reliability checks** executes 16 synthetic scenarios, including rejection cases. **Listen to plan** reads the week through browser speech when supported.

Fixture guide confirmations on Tuesday and Saturday are simulated. The athlete profile assumes access to a treadmill. These assumptions must be replaced with athlete-confirmed preferences before a pilot.

## Optional extras

`requirements.lock` installs everything the API, the planner, the Claude path and both dashboards' data layer need. Two heavier pieces are deliberately kept out of the lockfile and are installed only if you want them:

```sh
.venv/bin/python -m pip install '.[perception]'   # ultralytics, opencv-python-headless
.venv/bin/python -m pip install '.[dashboard]'    # streamlit
```

`perception` is required only by `runsense/perception.py`, which imports it lazily, so the server, the obstacle-triage logic in `runsense/triage.py` and its fixture harness all run without it. Installing the extra does not produce any measured detection result; the closing paragraph of this file says what is and is not known about perception.

`dashboard` installs Streamlit for the cross-run viewer below. Streamlit pins `websockets<17` while `requirements.lock` resolves 17.1, so installing this extra downgrades websockets. Uvicorn works with either version, but use a separate environment if that matters to you.

## Verify

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m runsense.evaluation
.venv/bin/python -m runsense.perception_eval
node --check runsense/static/app.js
```

203 pytest tests pass on 13 September 2026. They cover constraint rejection, sparse histories, duplicate prevention, persistence/replay, API authorization, provider failures, HTTP adapter contracts, the typed trace/alert tables, the obstacle-triage state machine and the Streamlit viewer's queries. The standalone evaluation runs 16 synthetic scenarios and exits nonzero if any fails. Its results do not measure clinical outcomes, real API availability, or perception accuracy.

`runsense.perception_eval` drives 10 procedurally generated detection sequences through the triage state machine and reports `"status": "triage_logic_tested"`. That status describes the logic, not a camera: it is not a recall, zone-accuracy, false-alert or latency measurement, and it must never be quoted as one.

## Architecture

```text
Athlete-authored Sheets log (synthetic fixture in demo)
    → deterministic planner OR bounded Claude input/proposal tool loop
    → independent Pydantic + planning-rule validation
    → saved, reviewable preview
    → approved Calendar upserts + read-back verification
    → Notion plan journal + persisted workflow result
    → accessible dashboard / user-triggered browser speech
```

FastAPI serves the API and dependency-free frontend. SQLite stores plans, action IDs and traces in `data/`; tokens and raw API responses are not persisted. Typed SQLAlchemy tables (`athletes`, `activities`, `plan_weeks`, `sessions`, `alerts`, `tool_traces`) live in the same database file alongside the original blob store rather than replacing it, so the API, the web dashboard and the evaluation harness keep reading exactly what they read before. There is one demo athlete, one fixed 09:00 Europe/Zurich scheduling slot, and one local executor. Cloud hosting, multi-user authorization, calendar conflict detection and durable distributed locks are outside this first build.

The primary app's Claude planning path exposes only `read_training_history`, `read_constraints`, and `propose_week`. A model in that path cannot call Calendar, send an invitation, or override the validation gate. It must read both inputs and return a valid proposal within six model requests. The default dashboard uses the deterministic planner; it does not pretend to invoke AI. The separate [Strava + Google Calendar LangChain service](strava_langchain_service/README.md) provides explicitly confirmed Calendar creation, read-back, and guide-RSVP tools for agent-driven scheduling.

That loop runs on LangChain's `ChatAnthropic` (`langchain`, `langchain-anthropic`, both in `requirements.lock`). The environment contract is unchanged — `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`, as before — and LangChain is an implementation detail, not a new credential. The six-request budget, the read-before-propose gate and the independent validation gate are preserved and still tested. A second tool set (`tts_say`, `session_start`, `session_end`, `sms_notify`, `perception_recent_alerts`) is declared for live-session work but is deliberately outside the planning loop; a test asserts the planning request never offers those tools to the model. `tts_say` and `sms_notify` reach the real providers described below; `session_start` and `session_end` are still stubs and return strings that say so.

## Live integration path

See [integration setup and contracts](docs/integrations.md) and [.env.example](.env.example). This prototype reads exported environment variables; it does not automatically load `.env` files.

The persistent three-app workflow uses **Google Sheets, Google Calendar, and Notion**. ElevenLabs is optional. Strava REST API data and third-party MCP wrappers are excluded: the [Strava API Policy](https://www.strava.com/legal/api_policy) restricts AI usage while making an exception for official MCP personal use. Do not fill the Sheet with exported Strava data and relabel it athlete-authored. A source column is an assertion by the operator, not a provenance detector.

### Official Strava MCP

Follow [the Strava MCP setup guide](docs/strava-mcp.md). Export an independently authorized `STRAVA_MCP_ACCESS_TOKEN`, start the server, and select **Check access** in the dashboard. Discovery lists the tools actually available to your account. Configure the activity tool, arguments and explicit field mapping from that schema, then restart and select **Plan with Strava**. A regular Strava REST API token is not interchangeable.

The new source reads `https://mcp.strava.com/mcp` directly using MCP initialization, tool listing and calls; it does not proxy the REST API. It supports JSON and SSE responses. Only a discovered tool with an explicit read-only annotation can be called. Distances/dates are parsed deterministically, non-running sports are excluded, repeated activity IDs are deduplicated, and invalid or explicitly paginated data is rejected. Tool names are never guessed. `POST /api/plan` with `{"source":"strava_mcp","use_llm":true}` uses the optional Claude planner after the same MCP read; the UI defaults to deterministic planning.

Personal Strava previews are isolated from demo data, labelled **You**, kept only in process memory for up to one hour, and cleared by local disconnect, detected authorization failure, token change, expiry or restart. They are not sent to Calendar or Notion by this version. Local disconnect does not revoke the OAuth grant; revoke it in Strava settings too. No raw activities or derived Strava previews are persisted in SQLite. The API requires the dashboard's HTTP-only session cookie or a configured admin bearer token for personal operations. This remains a local single-user prototype.

Strava subscription, account rollout, OAuth client admission, and actual tool response shape are provider-controlled. Only public unauthenticated MCP metadata has been checked live; no subscription grant or authenticated history call has been verified. The documented token-acquisition flow is explicit setup, not automatic token refresh. There is no fallback that silently replaces failed Strava calls with synthetic history.

Create a Sheet with a `Training` tab and columns `date, km, kind, completed, source`. Use ISO dates, kilometres, a boolean completion value, and `athlete_authored` as the source for independently recorded entries. Create a Notion data source with `Name` (title), `Plan ID` (rich text), and `Summary` (rich text); share it with the integration. Google consent/token acquisition, automatic refresh, and provider setup are not implemented. Access tokens must be supplied externally.

After configuring the provider variables, use a separate live database and set `RUNSENSE_MODE=live` plus a strong `RUNSENSE_ADMIN_TOKEN`. The live API requires `Authorization: Bearer <your token>`; use an HTTP client rather than the demo dashboard, which intentionally has no token input. Keep tokens out of chat and version control.

1. `POST /api/plan` with `{"scenario":"baseline","use_llm":true}` reads Sheets and proposes a week. Configure `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` first; set `use_llm:false` for a deterministic preview.
2. Read the returned plan and trace. Live guide RSVP polling is deferred, so all live workouts remain indoors.
3. `POST /api/commit` with `{"run_id":"<reviewed run>","approved":true}` writes and verifies Calendar events, then upserts Notion. All calendar writes omit attendees and use `sendUpdates=none`.
4. `GET /api/runs/<run_id>` returns the saved result. On a partial failure, inspect the trace and retry that same run. New previews supersede older uncommitted previews.

The workflow is not atomic across providers. Earlier successful calendar writes can remain after a later failure. Replanning a scheduled workout into a rest day is blocked until event-cancellation support is implemented. Do not claim exactly-once delivery across restarts/providers or a live guide coordination loop yet. See the integration document for Notion's uncertain-create limitation.

## Spoken cues and SMS notices

Both delivery channels are optional and both are honest when unconfigured: they return a marker string rather than raising or reporting a delivery that did not happen.

`tts_say` calls ElevenLabs and caches the returned MP3 on disk under `RUNSENSE_AUDIO_DIR` (default `data/audio`), keyed by a hash of text plus voice plus model, so repeating a cue reuses the bytes and never bills the provider twice. `GET /api/audio/{clip_id}` streams a cached clip back. With any of the three credentials missing, the tool returns `tts_not_configured`. The browser dashboard's **Listen to plan** button still uses user-triggered browser speech and does not call this API.

`sms_notify` posts to Twilio, and the guide-cancellation adaptation sends a reschedule notice to `RUNSENSE_GUIDE_PHONE` when all four values are set. Without them the trace records a skipped step explaining what to configure. Sends are not retried: the Twilio API has no idempotency key, so a retry could duplicate a message.

Export these alongside the existing variables; see [.env.example](.env.example), which already lists them:

```sh
ELEVENLABS_API_KEY=      ELEVENLABS_VOICE_ID=     ELEVENLABS_MODEL_ID=    RUNSENSE_AUDIO_DIR=data/audio
TWILIO_ACCOUNT_SID=      TWILIO_AUTH_TOKEN=       TWILIO_FROM_NUMBER=     RUNSENSE_GUIDE_PHONE=
```

Neither provider has been called with real credentials from this repository. Both clients are covered by `httpx.MockTransport` tests only — the same standard of evidence as the Sheets, Calendar and Notion adapters, and not a live-service verification.

## Cross-run trace and alert view

`runsense/observability.py` mirrors in-memory tool traces and perception alerts into the typed `tool_traces` and `alerts` tables. The in-memory trace dicts and the blob run rows are unchanged; this is a second, queryable write path. Recording is best-effort: a failure is reported, never raised, so a locked or read-only database cannot void an otherwise valid plan, commit or alert stream. That non-fatal behavior is tested with injected failures. `GET /api/traces` and `GET /api/alerts` expose the tables over the API.

A small Streamlit page reads the same tables directly:

```sh
.venv/bin/python -m pip install '.[dashboard]'
streamlit run dashboard/app.py
```

It answers the question the bundled per-run dashboard at `/` cannot: what happened *across* runs and sessions. It opens the SQLite file named by `RUNSENSE_DB` rather than going through the API, so it works against a database the server is not currently serving. It supplements the existing web dashboard, which remains the per-run plan/trace/evaluation view.

## Mobile app scaffold

`mobile/` contains an Expo Router and TypeScript React Native app of the plan's three screens — Today, Live run, Week plan — built to the accessibility spec and calling this repository's FastAPI backend rather than duplicating planning logic. Its TypeScript code and Jest triage tests pass, but **it has never been built or run on a device, simulator, emulator, Expo Go, or web target**. Camera/model inference, microphone permissions, OS recognition, and native audio remain runtime-unverified. Setup, the backend base-URL resolution order and the LAN/CORS constraints are in [mobile/README.md](mobile/README.md).

`scripts/export_yolo_tflite.py` is offline tooling for producing an on-device detector export. It is documented and has not been run; no exported model exists in this repository.

## Submission materials and next milestones

- [Evaluation against the actual hackathon brief](docs/hackathon-evaluation.md)
- [Two-minute demo script](docs/demo-script.md)
- [System and reliability brief](docs/system-reliability-brief.md)

Before submission: connect and verify all three apps, exercise the Claude path with credentials, implement actual guide consent/RSVP handling, and record the two-minute demo. Confirm the organizer's full rules, including pre-event code eligibility. The published event has a 6½-hour build window; the original PDF's 48-hour plan is oversized.

Obstacle *triage* logic is implemented and unit tested: `runsense/triage.py` decides zone, distance bucket and alert tier and applies the debounce, re-announcement and DANGER pre-emption rules, checked by 48 unit tests and 10 synthetic fixture sequences. That is the decision layer only. The detector wrapper in `runsense/perception.py` has never been run — there is no camera, no labelled footage and no on-device execution in this environment — so detection recall, zone and distance accuracy against ground truth, false-alert rate and end-to-end capture-to-audio latency are **still not measured**. The plan's under-400 ms budget and its golden-clip recall target remain unsubstantiated and must not be reported. Mobile camera inference, navigation and low-light support are not implemented. The 10% volume cap is a prototype constraint, not injury-prevention evidence. RunSense does not replace a guide or provide a medical training prescription.

## Edge-inference phase status

The mobile edge path now contains a TypeScript port of triage, a YOLO11 TFLite decoder, VisionCamera/fast-tflite frame-processor wiring, on-device OS speech recognition for Ask coach, local Expo speech/earcon delivery, and a recorded session-change request route. `npm run typecheck` and `npm test` pass, and the generated earcons pass WAV validation. The native camera, TFLite, microphone, speech-recognition, and playback paths are not verified because this machine has no full Xcode, iOS simulator, Android SDK, or device.

The export script downloaded YOLO11n and confirmed its output shape is `(1, 84, 8400)`, which grounds the decoder. LiteRT conversion failed on the available Python 3.14/Torch stack with `aten.cholesky` missing, so `mobile/assets/models/yolo11n.tflite` is not present. Re-run the export in a supported Python/Torch environment before creating a native build. The decoder and mobile wiring are therefore compile-verified, not runtime-verified.
