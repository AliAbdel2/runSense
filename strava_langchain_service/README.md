# RunSense Strava + Google Calendar LangChain service

A standalone Python service that calculates live pace and distance from phone
GPS samples, exports completed runs as TCX, optionally uploads them to Strava,
and creates training sessions in Google Calendar. Strava, Calendar, and
live-session operations are exposed as LangChain tools and HTTP endpoints. It
does not import or depend on the existing RunSense application.

Keep the written Strava approval for REST data in the AI workflow with the
project records and follow any limits stated in it. Upload is never automatic:
finishing a session and publishing it to Strava are separate operations.
Calendar writes likewise require explicit confirmation in the current request.

## Included tools

| LangChain tool | Purpose |
| --- | --- |
| `strava_get_athlete` | Check the authenticated athlete and return a minimal profile |
| `strava_get_training_history` | Normalize 1-52 weeks of runs for training-load analysis |
| `strava_get_activity` | Compare a completed activity with its planned session |
| `strava_get_activity_laps` | Analyze watch-recorded intervals and splits |
| `strava_get_activity_streams` | Read time, distance, velocity, HR, movement, cadence, or altitude |
| `strava_get_hr_zones` | Read configured HR and power zones |
| `strava_verify_completed_run` | Match a new upload by time and compare completed distance |
| `calendar_create_session` | Idempotently create/update an event, reminders, and optional guide invite |
| `calendar_get_session` | Read an event back to verify its saved state |
| `calendar_check_guide` | Check the invited guide's accepted/declined/tentative/pending response |
| `runsense_start_session` | Start a local live GPS session without writing to Strava |
| `runsense_get_live_metrics` | Return current distance and pace in numeric and spoken forms |
| `runsense_finish_session` | Finish the local recording without publishing it |
| `runsense_upload_session_to_strava` | Upload a finished TCX only after explicit owner confirmation |

`latlng` is intentionally not an agent stream. The LangChain tools normalize
activity data and omit maps and coordinates. The raw HTTP proxy exists for
developer inspection in Postman and should not be passed directly to the LLM.

## Setup

From this directory, create a virtual environment and install the package:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
```

Fill `.env`, then export it into the shell that starts the server:

```sh
set -a
source .env
set +a
.venv/bin/uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the generated OpenAPI interface.
`RUNSENSE_API_KEY` is required for every `/v1` route; `/health` remains public.

Required Strava scopes:

```text
activity:read_all
activity:write
```

`activity:write` is required only for optional session upload. Add
`profile:read_all` only if `strava_get_hr_zones` is needed. Access-token
creation and refresh are intentionally outside this service; update
`STRAVA_ACCESS_TOKEN` with your authorized token before it expires.

`ANTHROPIC_API_KEY` and an explicit `ANTHROPIC_MODEL` are required only for
`POST /v1/agent/chat`. All provider routes and individual LangChain tool routes
work without an LLM key.

For Google Calendar, provide `GOOGLE_CALENDAR_ACCESS_TOKEN` and optionally
`GOOGLE_CALENDAR_ID` (default `primary`). The token needs this OAuth scope:

```text
https://www.googleapis.com/auth/calendar.events
```

`GOOGLE_ACCESS_TOKEN` is accepted as a compatibility fallback. OAuth consent,
token refresh, and secure token storage stay outside this service; use a
dedicated test account/calendar for the hackathon rehearsal.

## Postman

Import both files:

- `postman/RunSense_Strava.postman_collection.json`
- `postman/RunSense_Strava.postman_environment.json`

For the Calendar-only workflow, import:

- `postman/RunSense_Calendar.postman_collection.json`
- `postman/RunSense_Calendar.postman_environment.json`

Select the **RunSense Strava Local** environment, then set:

- `strava_access_token`: the Strava access token used for direct provider calls.
- `runsense_api_key`: the same value as `RUNSENSE_API_KEY`.
- `session_start`: the planned session start in ISO 8601 form, if testing upload matching.
- `expected_distance_m`: expected workout distance in metres.

The collection contains four folders:

1. **Direct Strava API** verifies credentials, scopes, endpoint paths, and
   provider status codes independently of Python.
2. **RunSense HTTP API** verifies the Python client and normalized response.
3. **Live Run + Optional Strava Upload** simulates GPS, reads live metrics,
   finishes locally, previews TCX, and performs the separately confirmed upload.
4. **LangChain Tool Invocation** invokes the exact tools offered to the agent.

Run **List Athlete Activities** or **Normalized Training History** first; its
test script saves the first returned ID to `activity_id` for subsequent lap,
stream, and detail requests.

## Example calls

List the tool schemas:

```sh
curl http://127.0.0.1:8000/v1/tools \
  -H "Authorization: Bearer $RUNSENSE_API_KEY"
```

Invoke a LangChain tool without calling the LLM:

```sh
curl -X POST http://127.0.0.1:8000/v1/tools/strava_get_training_history/invoke \
  -H "Authorization: Bearer $RUNSENSE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"arguments":{"weeks":4,"per_page":100}}'
```

Ask the LangChain agent:

```sh
curl -X POST http://127.0.0.1:8000/v1/agent/chat \
  -H "Authorization: Bearer $RUNSENSE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Summarize my last four weeks and mention missing heart-rate data."}'
```

Ask the agent to create a Calendar event (this current message is the explicit
write confirmation):

```sh
curl -X POST http://127.0.0.1:8000/v1/agent/chat \
  -H "Authorization: Bearer $RUNSENSE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Create a treadmill run on 15 September 2026 from 09:00 to 10:00 Europe/Zurich. Remind me 60 and 10 minutes before."}'
```

For deterministic testing without an LLM, invoke the same tool directly:

```sh
curl -X POST http://127.0.0.1:8000/v1/tools/calendar_create_session/invoke \
  -H "Authorization: Bearer $RUNSENSE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"arguments":{"title":"RunSense treadmill run","start":"2026-09-15T09:00:00+02:00","end":"2026-09-15T10:00:00+02:00","time_zone":"Europe/Zurich","idempotency_key":"athlete:2026-09-15:treadmill","owner_confirmed":true,"venue_type":"treadmill","reminder_minutes":[60,10]}}'
```

The key hashes to a deterministic Google event ID. Retrying the same session
patches its owned event instead of creating a duplicate, and RunSense refuses
to overwrite an event without the matching private marker. With a
`guide_email`, Calendar receives `sendUpdates=all`; without one it receives
`sendUpdates=none`. A guide invitation remains provisional until
`calendar_check_guide` reports `accepted`.

Every successful provider call includes the upstream HTTP status and available
Strava rate-limit headers under `meta`. Provider error bodies and credentials
are never returned by the service.

## Live session flow

The phone client owns GPS collection. Send one or more timestamped locations to
the service; a batch is capped at 200 samples so a temporarily offline phone can
catch up safely.

```sh
# 1. Start locally. Save session_id from the response.
curl -X POST http://127.0.0.1:8000/v1/sessions \
  -H "Authorization: Bearer $RUNSENSE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Accessible Morning Run","sport_type":"Run"}'

# 2. Send GPS samples from the phone.
curl -X POST http://127.0.0.1:8000/v1/sessions/SESSION_ID/samples \
  -H "Authorization: Bearer $RUNSENSE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"samples":[{"timestamp":"2026-09-13T08:00:00Z","latitude":47.3769,"longitude":8.5417,"accuracy_m":5}]}'

# 3. Read current metrics suitable for speech output.
curl http://127.0.0.1:8000/v1/sessions/SESSION_ID/live \
  -H "Authorization: Bearer $RUNSENSE_API_KEY"

# 4. Finish locally. This does not contact Strava.
curl -X POST http://127.0.0.1:8000/v1/sessions/SESSION_ID/finish \
  -H "Authorization: Bearer $RUNSENSE_API_KEY" \
  -H 'Content-Type: application/json' -d '{}'

# 5. Publish only after an explicit owner command.
curl -X POST http://127.0.0.1:8000/v1/sessions/SESSION_ID/strava-upload \
  -H "Authorization: Bearer $RUNSENSE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"owner_confirmed":true,"description":"Recorded by RunSense"}'
```

For push updates, connect to
`ws://127.0.0.1:8000/v1/sessions/SESSION_ID/stream` with the same Bearer header.
The first message is the current snapshot; later messages arrive when samples
or session state change.

The live response intentionally omits coordinates while exposing
`current_pace_spoken` and a complete `spoken_status` sentence for deterministic
text-to-speech. Pace uses a rolling
10-second GPS window. Samples with worse than 50 metre accuracy, non-increasing
timestamps, or implausible running speed are rejected. Pause/resume boundaries
become separate TCX tracks so off-session movement is not counted.

Session storage is in memory for this branch because the main application owns
the database architecture. Restarting the service clears sessions. The
`LiveSessionManager` boundary is the intended persistence integration point.

Strava processes uploads asynchronously. The first upload response contains an
upload ID; poll `GET /v1/sessions/SESSION_ID/strava-upload` until `activity_id`
is populated or `error` is non-null. Repeating the confirmed POST is
idempotent within the running service and returns the original upload instead
of creating a duplicate.

## Tests

```sh
.venv/bin/python -m pytest -q
```

The tests use `httpx.MockTransport`; they do not contact Strava, Google, or Anthropic.
They cover GPS filtering, rolling pace, pause/resume distance, TCX generation,
owner confirmation, upload polling, duplicate-upload prevention, Calendar
payloads, guide status, and event idempotency/ownership checks.

## Implementation references

The upload contract was cross-checked against the official Strava Uploads API
and the Apache-licensed `stravalib` implementation. GPS outlier handling was
informed by the Apache-licensed `gpxpy` project's documented filtering
approach. Neither package is a runtime dependency.

- Strava API: https://developers.strava.com/docs/reference/#api-Uploads-createUpload
- Google Calendar events: https://developers.google.com/calendar/api/v3/reference/events
- Google Calendar create events: https://developers.google.com/workspace/calendar/api/guides/create-events
- stravalib: https://github.com/stravalib/stravalib
- gpxpy: https://github.com/tkrajina/gpxpy
