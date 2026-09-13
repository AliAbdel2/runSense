# RunSense Strava + LangChain service

A standalone Python service that reads approved athlete data from Strava,
exposes it as LangChain tools, and makes the same operations testable through
Postman. It does not import or depend on the existing RunSense application.

The service is read-only. Keep the written Strava approval for REST data in the
AI workflow with the project records and follow any limits stated in it.

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

Required Strava scope:

```text
activity:read_all
```

Add `profile:read_all` only if `strava_get_hr_zones` is needed. No write scope
is used. Access-token creation and refresh are intentionally outside this
service; update `STRAVA_ACCESS_TOKEN` with your authorized token before it
expires.

`ANTHROPIC_API_KEY` and an explicit `ANTHROPIC_MODEL` are required only for
`POST /v1/agent/chat`. All Strava routes and individual LangChain tool routes
work without an LLM key.

## Postman

Import both files:

- `postman/RunSense_Strava.postman_collection.json`
- `postman/RunSense_Strava.postman_environment.json`

Select the **RunSense Strava Local** environment, then set:

- `strava_access_token`: the Strava access token used for direct provider calls.
- `runsense_api_key`: the same value as `RUNSENSE_API_KEY`.
- `session_start`: the planned session start in ISO 8601 form, if testing upload matching.
- `expected_distance_m`: expected workout distance in metres.

The collection contains three folders:

1. **Direct Strava API** verifies credentials, scopes, endpoint paths, and
   provider status codes independently of Python.
2. **RunSense HTTP API** verifies the Python client and normalized response.
3. **LangChain Tool Invocation** invokes the exact tools offered to the agent.

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

Every successful provider call includes the upstream HTTP status and available
Strava rate-limit headers under `meta`. Provider error bodies and credentials
are never returned by the service.

## Tests

```sh
.venv/bin/python -m pytest -q
```

The tests use `httpx.MockTransport`; they do not contact Strava or Anthropic.
