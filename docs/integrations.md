# RunSense integrations

RunSense uses small asynchronous `httpx` clients with plain dictionary
contracts. Every client accepts an optional `httpx.AsyncBaseTransport`, so the
application and tests can run without live network calls or credentials.

The supported providers are Google Sheets, Google Calendar, Notion, and
ElevenLabs. Google uses an OAuth access token supplied by the application in
`GOOGLE_ACCESS_TOKEN`. OAuth bootstrap, consent, token refresh, and secure
credential storage are deliberately outside this module and remain deferred.

## Configuration

`Settings.from_env()` reads these uppercase variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `GOOGLE_ACCESS_TOKEN` | — | OAuth bearer token for Sheets and Calendar |
| `SHEETS_SPREADSHEET_ID` | — | Training workbook ID |
| `SHEETS_RANGE` | `Training!A1:E100` | Activity range |
| `GOOGLE_CALENDAR_ID` | `primary` | Calendar to manage |
| `NOTION_API_KEY` | — | Notion integration token |
| `NOTION_DATA_SOURCE_ID` | — | Notion plan data source |
| `NOTION_VERSION` | `2026-03-11` | Notion API version |
| `NOTION_TITLE_PROPERTY` | `Name` | Title property |
| `NOTION_PLAN_ID_PROPERTY` | `Plan ID` | Rich text identity property |
| `NOTION_SUMMARY_PROPERTY` | `Summary` | Rich text summary property |
| `ELEVENLABS_API_KEY` | — | ElevenLabs API key |
| `ELEVENLABS_VOICE_ID` | — | ElevenLabs voice |
| `ELEVENLABS_MODEL_ID` | — | ElevenLabs model |

Missing optional provider configuration produces an `IntegrationError` when
that provider is called. Error messages contain only a provider name, safe
message, and optional HTTP status; tokens and raw provider bodies are never
returned.

## Contracts and safety rules

`SheetsClient.get_activities()` reads rows with the columns `date`, `km`,
`kind`, `completed`, and `source`. It accepts only rows whose source is exactly
`athlete_authored`; Strava and other third-party-derived data are rejected.

`CalendarClient.upsert_session(session)` creates a deterministic event ID from
the session ID and schedules it at 09:00 in `Europe/Zurich` by default. A
session may provide an optional `start_time` such as `08:30`. The event has no
attendees and every write uses `sendUpdates=none`, so no guide invitation is
sent. On an ID conflict, the existing event must carry RunSense's private
session marker before it can be patched.

`NotionClient.upsert_plan(plan)` first queries the configured data source by the
`Plan ID` rich text property, then patches the matching page or creates one
with `Name`, `Plan ID`, and `Summary` properties. An ambiguous duplicate Plan
ID is an error. If a create races and returns 409, the client queries again and
patches the reconciled page; it never blindly retries a create. A 5xx response,
429 response, or transport timeout during creation is treated as an uncertain
outcome and reconciled the same way. If the follow-up query finds no page, the
client fails safely so a later application-level retry can decide whether to
continue. A durable creation journal is an application responsibility.

`NotionClient.get_plan(page_id)` retrieves a page for application-level
read-back verification after a write.

`ElevenLabsClient.synthesize(text)` returns the provider's audio bytes for the
configured voice and model. All clients retry transient 429 and 5xx responses
with a bounded delay. Tests use `httpx.MockTransport`; no live requests are
made by this repository's integration tests.

These clients intentionally provide no Strava integration. Strava's June 2026
API policy restricts AI operation on API data, including context and derived
data, so athlete-authored Sheets rows are the supported activity source for
this build.
