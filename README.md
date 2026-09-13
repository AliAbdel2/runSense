# RunSense

A guide-aware training coordination prototype for blind and low-vision runners. Plan a week, inspect why a session was chosen, hear it aloud, and replay a guide cancellation or missed-session scenario.

**Current state:** a working local demo with synthetic data, a deterministic planner, durable traces and simulated Calendar/Notion actions. The official Strava MCP client now supports authenticated tool discovery and personal activity-based previews. An optional Claude tool loop and real HTTP adapters are implemented and tested with mock transports. No external accounts are connected or live-verified. This is not yet an eligible three-connected-app hackathon submission.

## Run locally

Python 3.11 or newer. From this directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m uvicorn runsense.main:app --host 127.0.0.1 --port 8000
```

Open [the dashboard](http://127.0.0.1:8000) or [API docs](http://127.0.0.1:8000/api/docs). No credentials are needed. Keep the server bound to localhost, with one worker.

1. **Plan my week** generates Sara's next Monday–Sunday plan using a 19 km recent weekly baseline.
2. **Guide cancelled** moves Tuesday to the treadmill, retaining the same event identity.
3. **Missed session** reduces weekly distance by 20% and replaces intervals with easy running.
4. **Simulate Calendar failure** records a simulated pre-write 503, followed by a successful retry.
5. **Run reliability checks** executes 16 synthetic scenarios, including rejection cases. **Listen to plan** reads the week through browser speech when supported.

Fixture guide confirmations on Tuesday and Saturday are simulated. The athlete profile assumes access to a treadmill. These assumptions must be replaced with athlete-confirmed preferences before a pilot.

## Verify

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m runsense.evaluation
node --check runsense/static/app.js
```

Tests cover constraint rejection, sparse histories, duplicate prevention, persistence/replay, API authorization, provider failures and HTTP adapter contracts. The standalone evaluation exits nonzero if any scenario fails. Its results do not measure clinical outcomes, real API availability, or perception accuracy.

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

FastAPI serves the API and dependency-free frontend. SQLite stores plans, action IDs and traces in `data/`; tokens and raw API responses are not persisted. There is one demo athlete, one fixed 09:00 Europe/Zurich scheduling slot, and one local executor. Cloud hosting, multi-user authorization, calendar conflict detection and durable distributed locks are outside this first build.

The Claude path exposes only `read_training_history`, `read_constraints`, and `propose_week`. A model cannot call Calendar, send an invitation, or override the validation gate. It must read both inputs and return a valid proposal within six model requests. The default dashboard uses the deterministic planner; it does not pretend to invoke AI.

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

## Submission materials and next milestones

- [Evaluation against the actual hackathon brief](docs/hackathon-evaluation.md)
- [Two-minute demo script](docs/demo-script.md)
- [System and reliability brief](docs/system-reliability-brief.md)

Before submission: connect and verify all three apps, exercise the Claude path with credentials, implement actual guide consent/RSVP handling, and record the two-minute demo. Confirm the organizer's full rules, including pre-event code eligibility. The published event has a 6½-hour build window; the original PDF's 48-hour plan is oversized.

Obstacle detection, mobile camera inference, navigation, low-light support and capture-to-audio latency are **not implemented or measured**. The 10% volume cap is a prototype constraint, not injury-prevention evidence. RunSense does not replace a guide or provide a medical training prescription.
