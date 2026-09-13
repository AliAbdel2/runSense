/**
 * TypeScript mirrors of the backend's Pydantic models and route envelopes.
 *
 * Every type in the first section is a hand-translation of a model in
 * `runsense/models.py`. Field names, optionality and `Literal[...]` unions are
 * copied exactly; Python `date` becomes an ISO `YYYY-MM-DD` string because
 * `model_dump(mode="json")` is what the routes actually return.
 *
 * The second section covers response envelopes that are assembled in
 * `runsense/agent.py` / `runsense/main.py` rather than declared as Pydantic
 * models. Those are intentionally described loosely where the backend itself is
 * loose (free-form `status` strings, for example) so this client does not
 * pretend to a stricter contract than the server offers.
 */

/* ------------------------------------------------------------------ *
 * runsense/models.py
 * ------------------------------------------------------------------ */

/** ISO-8601 calendar date, e.g. "2026-09-14". Python `datetime.date`. */
export type IsoDate = string;

/** `Activity.source: Literal["athlete_authored", "synthetic", "strava_mcp"]` */
export type ActivitySource = 'athlete_authored' | 'synthetic' | 'strava_mcp';

/** `runsense.models.Activity` */
export interface Activity {
  date: IsoDate;
  /** `Field(ge=0, le=200)` */
  km: number;
  /** `Field(default="easy", max_length=40)` */
  kind: string;
  completed: boolean;
  source: ActivitySource;
}

/** `Session.kind: Literal["easy", "intervals", "long", "rest"]` */
export type SessionKind = 'easy' | 'intervals' | 'long' | 'rest';

/** `Session.venue: Literal["treadmill", "track", "park", "home"]` */
export type Venue = 'treadmill' | 'track' | 'park' | 'home';

/** `Session.guide_status: Literal["accepted", "pending", "declined", "not_required"]` */
export type GuideStatus = 'accepted' | 'pending' | 'declined' | 'not_required';

/** `runsense.models.Session` */
export interface Session {
  id: string;
  athlete_id: string;
  date: IsoDate;
  kind: SessionKind;
  /** `Field(ge=0, le=100)` */
  km: number;
  venue: Venue;
  guide_status: GuideStatus;
  /** `Field(min_length=1, max_length=240)` */
  spoken_summary: string;
  /** `Field(min_length=1, max_length=600)` */
  rationale: string;
}

/** `runsense.models.Plan` */
export interface Plan {
  id: string;
  week_start: IsoDate;
  athlete_name: string;
  goal: string;
  week_km: number;
  baseline_km: number;
  scenario: string;
  /** `Field(min_length=1, max_length=1200)` */
  rationale: string;
  /** `Field(min_length=7, max_length=7)` — always exactly seven, Monday first. */
  sessions: Session[];
}

/** `PlanRequest.scenario` literal union. */
export type Scenario = 'baseline' | 'guide_cancelled' | 'missed_session' | 'calendar_retry';

/** `PlanRequest.source: Literal["default", "strava_mcp"]` */
export type PlanSource = 'default' | 'strava_mcp';

/**
 * `runsense.models.PlanRequest`. Every field has a server-side default, and the
 * model is `extra="forbid"`, so send only the keys you mean to override.
 */
export interface PlanRequest {
  scenario?: Scenario;
  week_start?: IsoDate | null;
  use_llm?: boolean;
  source?: PlanSource;
}

/** `runsense.models.CommitRequest` */
export interface CommitRequest {
  run_id: string;
  approved: boolean;
}

/* ------------------------------------------------------------------ *
 * Response envelopes assembled in agent.py / main.py
 * ------------------------------------------------------------------ */

/** One entry of `validate_plan(...)["checks"]` in `runsense/planner.py`. */
export interface ValidationCheck {
  name: string;
  passed: boolean;
  detail: string;
}

/** Return value of `runsense.planner.validate_plan`. */
export interface Validation {
  passed: boolean;
  checks: ValidationCheck[];
}

/**
 * One agent trace step. The dict shape is fixed by the LangChain tool loop and
 * consumed identically by `runsense/static/app.js:renderTrace`. `status` is a
 * free-form string on the server ("completed", "retrying", "skipped", ...), so
 * it stays a string here rather than a union that would drift.
 */
export interface TraceStep {
  tool: string;
  status: string;
  attempt?: number;
  latency_ms?: number;
  detail?: string;
  /** app.js falls back to `name` before `tool`; some steps carry it. */
  name?: string;
}

/** Entries appended to `result["calendar_events"]` by the agent. */
export interface CalendarEvent {
  id: string;
  status: string;
  session_id?: string;
}

/** `result["mode"]` as set in `agent.py`. */
export type RunMode = 'demo' | 'live_preview' | 'strava_preview';

/**
 * The object returned by `GET /api/demo`, `POST /api/plan`, `POST /api/commit`
 * and `GET /api/runs/{run_id}` (the latter two after `Agent.public`, which
 * strips `history` and `guides`).
 */
export interface RunResult {
  run_id: string;
  mode: RunMode;
  planner: 'deterministic' | 'claude';
  plan: Plan;
  validation: Validation;
  trace: TraceStep[];
  calendar_events: CalendarEvent[];
  audio_url: string | null;
  committed: boolean;
  /** Present on Strava personal previews only. */
  source?: PlanSource;
  retention?: string;
  expires_in_seconds?: number;
}

/** One row of `GET /api/status`'s `integrations`. */
export interface IntegrationStatus {
  name: string;
  status: string;
  detail: string;
}

/** `GET /api/status` */
export interface StatusResponse {
  mode: 'demo' | 'live';
  llm_configured: boolean;
  integrations: IntegrationStatus[];
}

/** `GET /api/strava/status` and `POST /api/strava/check` / `.../disconnect`. */
export interface StravaStatus {
  status: string;
  detail: string;
  tool_configured?: boolean;
  tools?: { name?: string; description?: string }[];
}

/** `runsense.perception_eval.evaluate_perception` */
export interface PerceptionReport {
  status: string;
  detail: string;
  fixtures_passed: number;
  fixtures_total: number;
  evidence: string;
  unmeasured: string[];
}

/** `POST /api/evaluate` — `runsense.evaluation.evaluate`. */
export interface EvaluationReport {
  /** Count of passing scenarios, not a boolean (see evaluation.py). */
  passed: number;
  total: number;
  results: { name: string; passed: boolean; detail: string }[];
  scope: string;
  perception: PerceptionReport;
}

/* ------------------------------------------------------------------ *
 * Perception alert shape (runsense/triage.py:AlertEvent.to_dict)
 * ------------------------------------------------------------------ */

/** `runsense.triage.Zone` */
export type AlertZone = 'left' | 'center' | 'right';

/** `runsense.triage.DistanceBucket` */
export type AlertDistance = 'near' | 'mid' | 'far';

/** `runsense.triage.Tier` */
export type AlertTier = 'danger' | 'warning' | 'notice' | 'silent';

/**
 * A single triage decision, matching `AlertEvent.to_dict()`.
 *
 * Produced by the mobile frame processor once the native model is loaded.
 */
export interface PerceptionAlert {
  frame_index: number;
  spoken_frame: number | null;
  track_id: number;
  obj_class: string;
  zone: AlertZone;
  distance: AlertDistance;
  tier: AlertTier;
  approaching: boolean;
  utterance: string;
  earcon: string;
  max_latency_ms: number | null;
  spoken: boolean;
  preempted: boolean;
}
