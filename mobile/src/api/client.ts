import { API_BASE_URL, REQUEST_TIMEOUT_MS } from './config';
import type {
  CommitRequest,
  EvaluationReport,
  PlanRequest,
  RunResult,
  StatusResponse,
  StravaStatus,
} from './types';

/**
 * Typed fetch wrapper over the RunSense FastAPI routes.
 *
 * Mirrors `runsense/static/app.js:request` — JSON in, JSON out, and the
 * server's `{"detail": "..."}` body is what becomes the error message, because
 * the backend deliberately writes those details for humans to read aloud.
 */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST';
  body?: unknown;
  /** Bearer token for live mode (`RUNSENSE_ADMIN_TOKEN`); unused in demo mode. */
  adminToken?: string;
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, adminToken, signal } = options;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const onOuterAbort = () => controller.abort();
  signal?.addEventListener('abort', onOuterAbort);

  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (adminToken) headers['Authorization'] = `Bearer ${adminToken}`;

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      const detail =
        payload && typeof payload === 'object' && 'detail' in payload
          ? String((payload as { detail: unknown }).detail)
          : `Request failed (${response.status}).`;
      throw new ApiError(detail, response.status);
    }
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof Error && error.name === 'AbortError') {
      throw new ApiError(
        `No answer from RunSense at ${API_BASE_URL}. Check the server is running and reachable from this device.`,
        0,
      );
    }
    throw new ApiError(
      `Could not reach RunSense at ${API_BASE_URL}. ${error instanceof Error ? error.message : String(error)}`,
      0,
    );
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', onOuterAbort);
  }
}

/** `GET /api/demo` — a synthetic baseline week; no auth, no writes. */
export function getDemoPlan(signal?: AbortSignal): Promise<RunResult> {
  return request<RunResult>('/api/demo', { signal });
}

/**
 * `POST /api/plan`.
 *
 * `source: "strava_mcp"` additionally requires the `runsense_personal` cookie
 * that the web dashboard receives from `GET /`. This app does not hold that
 * cookie, so personal Strava previews are a dashboard-only path for now.
 */
export function createPlan(body: PlanRequest = {}, options: Omit<RequestOptions, 'method' | 'body'> = {}): Promise<RunResult> {
  return request<RunResult>('/api/plan', { method: 'POST', body, ...options });
}

/** `POST /api/commit` — live mode only; rejected with 409 in demo mode. */
export function commitRun(body: CommitRequest, options: Omit<RequestOptions, 'method' | 'body'> = {}): Promise<RunResult> {
  return request<RunResult>('/api/commit', { method: 'POST', body, ...options });
}

/** `GET /api/runs/{run_id}` */
export function getRun(runId: string, options: Omit<RequestOptions, 'method' | 'body'> = {}): Promise<RunResult> {
  return request<RunResult>(`/api/runs/${encodeURIComponent(runId)}`, options);
}

/** `POST /api/evaluate` */
export function runEvaluation(signal?: AbortSignal): Promise<EvaluationReport> {
  return request<EvaluationReport>('/api/evaluate', { method: 'POST', signal });
}

/** `GET /api/status` */
export function getStatus(signal?: AbortSignal): Promise<StatusResponse> {
  return request<StatusResponse>('/api/status', { signal });
}

/** `GET /api/strava/status` — needs the dashboard's personal-session cookie. */
export function getStravaStatus(options: Omit<RequestOptions, 'method' | 'body'> = {}): Promise<StravaStatus> {
  return request<StravaStatus>('/api/strava/status', options);
}

/** `POST /api/strava/check` — needs the dashboard's personal-session cookie. */
export function checkStrava(options: Omit<RequestOptions, 'method' | 'body'> = {}): Promise<StravaStatus> {
  return request<StravaStatus>('/api/strava/check', { method: 'POST', ...options });
}

/** `POST /api/strava/disconnect` — needs the dashboard's personal-session cookie. */
export function disconnectStrava(options: Omit<RequestOptions, 'method' | 'body'> = {}): Promise<StravaStatus> {
  return request<StravaStatus>('/api/strava/disconnect', { method: 'POST', ...options });
}

/**
 * `GET /api/audio/{clip_id}` returns raw `audio/mpeg` bytes, so it is a URL to
 * hand to a player rather than something to parse. Nothing in this scaffold
 * plays audio yet: wiring `expo-av`/`expo-audio` is a later phase.
 */
export function audioClipUrl(clipId: string): string {
  return `${API_BASE_URL}/api/audio/${encodeURIComponent(clipId)}`;
}

export function askCoach(question: string, athleteId = 'sara'): Promise<{ answer: string; audio_clip_id: string | null }> {
  return request('/api/coach/ask', { method: 'POST', body: { question, athlete_id: athleteId } });
}

export function requestSessionChange(sessionId: string, requestText: string): Promise<{ status: string; detail: string }> {
  return request(`/api/sessions/${encodeURIComponent(sessionId)}/change-request`, { method: 'POST', body: { request: requestText } });
}
