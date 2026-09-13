import type { Plan, Session } from '@/api/types';

/**
 * Wording helpers ported from `runsense/static/app.js` so the phone and the web
 * dashboard describe the same plan with the same words. `sessionLabel`,
 * `humanStatus` and `formatKm` are direct ports; the sentence builders below
 * are new, because a screen reader wants one sentence per row where the web
 * dashboard uses a grid of cells.
 */

const STATUS_LABELS: Record<string, string> = {
  accepted: 'Guide confirmed (demo)',
  declined: 'Guide declined',
  pending: 'No guide confirmed',
  not_required: 'No guide needed',
  not_connected: 'Not connected',
  configured_unverified: 'Configured · unverified',
  connected: 'Connected',
  access_denied: 'Access denied',
  error: 'Connection error',
  demo: 'Demo',
};

/** app.js:humanStatus */
export function humanStatus(value: string | null | undefined): string {
  const raw = String(value ?? '');
  const known = STATUS_LABELS[raw.toLowerCase()];
  if (known) return known;
  const spaced = raw.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  return spaced || 'Status unavailable';
}

/** app.js:sessionLabel */
export function sessionLabel(session: Pick<Session, 'kind'>): string {
  const kind = String(session.kind ?? 'Run').toLowerCase();
  if (kind === 'rest' || kind === 'recovery') return 'Recovery day';
  if (kind === 'intervals') return 'Intervals';
  if (kind === 'long') return 'Long run';
  if (kind === 'easy') return 'Easy run';
  return humanStatus(session.kind);
}

/** app.js:formatKm */
export function formatKm(km: number | null | undefined): string {
  return km === undefined || km === null ? '—' : `${km} km`;
}

/** app.js:formatDate — parsed at noon so a timezone shift cannot move the day. */
export function formatDate(value: string | null | undefined, options?: Intl.DateTimeFormatOptions): string {
  if (!value) return '—';
  const parsed = new Date(`${value}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, options ?? { weekday: 'long', month: 'long', day: 'numeric' });
}

/** Short weekday, e.g. "Tue". Used as the visual day chip on the week list. */
export function weekdayShort(value: string | null | undefined): string {
  if (!value) return 'Day';
  const parsed = new Date(`${value}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return 'Day';
  return parsed.toLocaleDateString(undefined, { weekday: 'short' });
}

/** True for the guide states the dashboard renders as "off"/needs attention. */
export function guideNeedsAttention(session: Pick<Session, 'guide_status'>): boolean {
  return session.guide_status === 'pending' || session.guide_status === 'declined';
}

/**
 * One sentence per session — the unit a screen reader reads for a week row.
 * Same facts and same vocabulary as the dashboard's week grid, joined into
 * prose: day, workout, distance, venue, guide status.
 */
export function sessionSentence(session: Session): string {
  const day = formatDate(session.date, { weekday: 'long', month: 'long', day: 'numeric' });
  const label = sessionLabel(session);
  const status = humanStatus(session.guide_status);
  if (session.kind === 'rest') {
    return `${day}. ${label}, no running planned. ${status}.`;
  }
  return `${day}. ${label}, ${formatKm(session.km)}, ${session.venue}. ${status}.`;
}

/**
 * The session the Home screen speaks. The dashboard picks "next" the same way:
 * first non-rest session, falling back to the first session of the week.
 * A real product would pick by today's date; this keeps parity with app.js,
 * whose demo week always starts next Monday.
 */
export function nextSession(plan: Plan | null): Session | null {
  if (!plan || plan.sessions.length === 0) return null;
  return plan.sessions.find((session) => session.kind !== 'rest') ?? plan.sessions[0] ?? null;
}

/** The full announcement spoken when the Home screen opens. */
export function todayAnnouncement(plan: Plan | null, session: Session | null): string {
  if (!plan || !session) return 'Today’s session is not available yet.';
  const opening = `${plan.athlete_name}, here is your next session.`;
  return `${opening} ${sessionSentence(session)} ${session.spoken_summary}`;
}
