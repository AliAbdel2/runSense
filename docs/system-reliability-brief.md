# System and reliability brief

RunSense coordinates a training week around a runner's history and guide constraints. The implementation uses FastAPI, a plain accessible web frontend, Pydantic validation and SQLite for non-Strava demo/Sheets runs. An official Strava MCP source now provides a separate personal preview path with in-memory retention only. No credentials were available during implementation; the delivered demo uses synthetic history and local simulations. Real adapters have HTTP mock tests, not authenticated live service evidence.

## Decision and execution boundaries

The planning input is an independently athlete-authored Google Sheets log. A deterministic planner or optional bounded Claude tool loop proposes seven days. Independent rules reject inconsistent dates or distances, excessive volume, consecutive hard days, invented guide confirmations, and long spoken summaries. Track sessions count as outdoors. Live mode assumes no guide confirmed until an actual RSVP workflow exists, so it schedules indoor sessions only.

The server stores a validated preview. The live executor requires authenticated approval of that saved run. It revalidates before writing. Calendar events have stable athlete/date IDs, private ownership markers, and read-back checks. Notion stores the plan and rationale under a stable Plan ID. All external actions occur server-side; credentials stay in environment variables. Calendar invitations and notifications are not sent by this prototype.

## Evidence available

- An executable 16-scenario synthetic evaluation covers ten athlete constraints, repeat execution, guide cancellation, missed-session adaptation, an injected simulated 503 and rejection cases.
- Pytest exercises production rules, persistent action identity, saved-run replay, API access controls and HTTP provider contracts.
- Baseline verification before the MCP addition on 13 September 2026: **42 pytest tests passed**, **16/16 evaluation scenarios passed**, JavaScript syntax check passed, and the dashboard rendered without horizontal overflow at a 390-pixel viewport. Two dependency deprecation warnings remain; no test failures.
- After the MCP implementation: **79 pytest tests passed**, including MCP session/protocol negotiation, streamed SSE completion, bounded responses, discovery, 401/403 handling, explicit read-only tool gating, token-rotation reconnect, field mapping, sport filtering, deduplication, memory-only previews, expiry and same-origin access. The existing **16/16** synthetic evaluation remains a separate planning check, not an MCP live-access test.
- The dashboard exposes step status, attempt number, measured local duration where available, and explicit descriptions of simulated calls. A zero duration is uninstrumented/sub-millisecond bookkeeping, not a device performance claim.
- Browser speech is user-triggered. Computer vision recall, zone accuracy, false alarms and end-to-end playback latency remain unmeasured.

Run `.venv/bin/python -m pytest -q` and `.venv/bin/python -m runsense.evaluation` from the repository. No test sends a real invitation or writes to a real app.

## Failure behavior and limitations

Transient HTTP status failures have bounded provider retries. Calendar ID conflicts require ownership verification before update. Notion queries by Plan ID and must reconcile ambiguous creates without blindly replaying POST. Cross-app writes are not transactional: earlier successful writes remain if a later step fails. Traces persist incremental progress; retries must use the same saved run. One in-process lock serializes live actions. Run a single worker; multi-process/restart guarantees need a durable execution lease and stronger provider reconciliation.

The demo is a single-athlete local prototype. OAuth bootstrap/refresh, live guide consent/RSVP, preferences, cancellation/removal of old calendar events, speech recognition, mobile camera use and accessibility testing with blind runners remain open. The three-app requirement is unmet until actual accounts are connected and verified. The optional LLM needs an authenticated smoke test; its HTTP mock tests alone do not demonstrate live AI behavior.

The Strava source uses an externally authorized MCP bearer token and discovered activity tool, with explicit field mapping. It neither accepts a Strava REST token as an equivalent nor silently substitutes fixtures when access fails. Strava-derived history is never put in SQLite, Calendar or Notion by this implementation. See [personal Strava MCP setup and boundaries](strava-mcp.md).
