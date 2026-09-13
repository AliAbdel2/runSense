# Personal Strava MCP source

RunSense has an optional personal activity source backed by Strava's official,
Strava controlled MCP server. It is intended for one local operator reading
that operator's own authorized Strava account. It is a read only preview
source: the preview can inform the local planner, but it cannot write back to
Strava, commit a plan, populate the Google or Notion integrations, or export a
Strava snapshot.

This path uses the server directly at
[`https://mcp.strava.com/mcp`](https://mcp.strava.com/mcp) over Streamable HTTP.
It does not use the Strava REST API, a third party MCP wrapper, a proxy, or a
REST fallback. The source is available only when the operator supplies a
separately obtained MCP OAuth bearer token and the account is eligible for the
Strava MCP rollout.

## Protocol and data flow

The client performs the following bounded protocol operations:

1. Open a Streamable HTTP session and send `initialize`.
2. Send `tools/list` and retain the tool names and metadata returned by this
   server.
3. Select the activity-history tool using `STRAVA_MCP_ACTIVITY_TOOL`.
4. Substitute the configured date arguments and send `tools/call`.
5. Decode the result. `structuredContent` is preferred; when it is absent the
   client accepts one JSON object or array in a single text content item.
6. Read the configured JSON pointer and map each row to RunSense's activity
   shape, with `source` explicitly set to `strava_mcp`.
7. Reject malformed rows before they reach either the deterministic planner or
   the optional local Claude planner.

The activity tool name is discovered at runtime and is never hardcoded. The
configured name must be present in the actual `tools/list` response. The
connection check reports the server and the tools actually discovered; a
successful protocol connection does not prove that this account has historical
activity eligibility.

RunSense selects a tool only when its discovery metadata includes the explicit
`annotations.readOnlyHint: true` flag. A missing or false read-only annotation,
an invalid destructive annotation, or an explicit `destructiveHint: true`, is
rejected before `tools/call`.

The adapter requires a finite, non-negative distance, a parseable date, and a
valid row object. It rejects a missing pointer, invalid JSON, non-finite values,
unsupported distance units, and rows that do not pass the explicit source
mapping. The configured distance is converted to kilometres for the existing
`Activity` model. The sport field filters running activities; it does not infer
workout intensity. Activity IDs are required for deduplication and are discarded
after normalization. Explicit pagination indicators fail closed rather than
silently treating partial history as a complete window.

## Configuration

These variables are read by the local server. Empty values are treated as
unset. Do not commit a token or place one in a chat transcript.

| Variable | Default | Purpose |
| --- | --- | --- |
| `STRAVA_MCP_ACCESS_TOKEN` | — | OAuth bearer issued for the Strava MCP; this is not a Strava REST API token. |
| `STRAVA_MCP_ACTIVITY_TOOL` | — | Exact tool name from the server's `tools/list` response. |
| `STRAVA_MCP_ACTIVITY_ARGUMENTS_JSON` | `{}` | JSON object sent to the activity tool, with the supported placeholders below. |
| `STRAVA_MCP_ROWS_POINTER` | `/activities` | JSON pointer to the activity row array in the tool result. |
| `STRAVA_MCP_DATE_FIELD` | `start_date_local` | Row field containing the activity date or local timestamp. |
| `STRAVA_MCP_DISTANCE_FIELD` | `distance` | Row field containing the distance. |
| `STRAVA_MCP_DISTANCE_UNIT` | `meters` | Unit of the distance field; the default is converted to kilometres. |
| `STRAVA_MCP_SPORT_FIELD` | `sport_type` | Row field used to include running sports only. |
| `STRAVA_MCP_ID_FIELD` | `id` | Required row field used to deduplicate activities. |

`STRAVA_MCP_ACTIVITY_ARGUMENTS_JSON` must be a JSON object. Its date values
may use these exact string placeholders; the client replaces them for the
requested history window:

```json
{
  "after": "${after_epoch}",
  "before": "${before_epoch}",
  "week_start": "${week_start}",
  "after_date": "${after_date}",
  "before_date": "${before_date}"
}
```

The server's discovered input schema remains authoritative. Configure only the
keys that the selected activity tool accepts, while keeping placeholder values
as strings exactly as shown. A malformed or non-object arguments value fails
closed before `tools/call`.

## OAuth setup

RunSense does not perform sign-in, register an OAuth client, or harvest a token
from Claude. Obtain an MCP token through an authorization flow that you control
and then provide that token to the local process as
`STRAVA_MCP_ACCESS_TOKEN`.

For a test authorization, Anthropic's MCP connector documentation describes the
MCP Inspector quick flow:

1. Run `npx @modelcontextprotocol/inspector`.
2. Choose **Streamable HTTP** and enter `https://mcp.strava.com/mcp`.
3. Open **Auth Settings**, choose **Quick OAuth Flow**, and complete the
   authorization in the browser.
4. Continue until authentication is complete and copy the resulting
   `access_token` into the local environment.

The server controls its grants. The public discovery metadata currently reports
the issuer as [`https://www.strava.com/mcp-issuer`](https://www.strava.com/mcp-issuer),
but this repository does not assume that a pre-registered custom OAuth client
exists or that the server will approve one. If Strava denies the Inspector or
custom client, that is a provider access limitation; do not extract credentials
from Claude or impersonate an approved client. Keep the demo available while
resolving approved access with Strava.

Strava's documented Claude Code setup is:

```sh
claude mcp add --transport http strava-mcp https://mcp.strava.com/mcp
```

That command configures Claude Code. It does not configure RunSense's
`STRAVA_MCP_ACCESS_TOKEN`, and completing consent in Claude does not make a
token available to this application. Claude.ai and Claude Cowork also expose a
Strava connector under **Customize → Connectors**; that is a separate
authorization path.

At the time of this implementation there is no live credential in the demo
environment, so the authenticated historical-activity path is not claimed as
live verified.

## UI and lifecycle

The dashboard exposes the personal source as an explicit `strava_mcp` option.
**Check access** performs discovery and displays the actual discovered
tools and current protocol status. It does not fabricate an activity result or
report historical eligibility from a handshake alone. **Plan with Strava**
requests a bounded history window for the operator's own account and shows the
plan, validation outcome, and source label. The optional
`use_llm=true` setting passes the validated in-memory history to the existing
Claude provider; it does not give Claude direct MCP access or add another MCP
server.

Strava rows and any derived preview are memory-only, with a maximum lifetime of
one hour. They are not written to the RunSense SQLite store, a Notion page, a
Google Sheet, a vector index, or an export file. **Disconnect** clears the
local in-memory connection and preview state; revoke the grant in Strava's
**Settings → My Apps** as well. Restart, local disconnect, token change,
detected authorization failure and expiry clear the in-memory preview. The UI
uses an HTTP-only, same-origin session cookie for personal operations. An admin
bearer token can also authorize API calls. There is no multi-user login system.

All commit and external-export actions that depend on a Strava preview remain
blocked pending policy review. A Strava preview therefore cannot be used to
write Calendar or Notion records, to seed a Google Sheets log, or to create a
public demo artifact.

## Policy boundary

Strava's [API Policy](https://www.strava.com/legal/api_policy) §3.5 identifies
the Strava MCP as the official Strava-controlled agent-mediated interface and
allows a subscriber to bring an AI application to interact with that
subscriber's own data for personal use. The same section excludes commercial
or third-party access outside the developer's own personal use. Sections 5.3
and 5.4 continue to restrict ordinary API data and derivatives in AI operation,
grounding, evaluation, analytics, and retrieval; the MCP exception does not
turn this local preview into permission to build a multi-user service.

The [Strava MCP help article](https://support.strava.com/en-us/articles/15401531-what-is-the-strava-mcp-connector)
describes the connector as read-only, subscriber-only, OAuth-authorized, and
subject to a gradual rollout and request limits. The operator must therefore
confirm subscription and account eligibility. One local personal account is in
scope for this prototype. Commercial deployment, multiple athletes, sharing a
token, exposing a wrapper or proxy, third-party access, bulk export, persistent
storage, and benchmarking Strava are out of scope and require separate policy
review and authorization.

The MCP source is an optional personal alternative to the independently
athlete-authored Google Sheets source. It does not impose a broad Strava ban,
and it does not change the app's honest distinction between a local preview and
a verified three-app workflow.
