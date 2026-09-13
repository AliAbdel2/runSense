export type Zone = 'left' | 'center' | 'right';
export type DistanceBucket = 'near' | 'mid' | 'far';
export type Tier = 'danger' | 'warning' | 'notice' | 'silent';

export const NEAR_RATIO = 0.45;
export const FAR_RATIO = 0.2;
export const PERSIST_FRAMES = 3;
export const CLEAR_FRAMES = 15;
export const APPROACH_WINDOW_FRAMES = 3;
export const APPROACH_GROWTH = 1.05;
export const FAST_GROWTH = 1.15;
export const MAX_LATENCY_MS: Record<string, number> = { danger: 400, warning: 600, notice: 1500 };

export interface Detection {
  frameIndex: number;
  trackId: number;
  objClass: string;
  x1: number; y1: number; x2: number; y2: number;
  frameWidth: number; frameHeight: number;
  confidence?: number;
}

export interface AlertEvent {
  frameIndex: number; spokenFrame: number | null; trackId: number; objClass: string;
  zone: Zone; distance: DistanceBucket; tier: Tier; approaching: boolean;
  utterance: string; earcon: string; maxLatencyMs: number | null;
  spoken: boolean; preempted: boolean;
}

export const centerXRatio = (d: Detection) => ((d.x1 + d.x2) / 2) / d.frameWidth;
export const heightRatio = (d: Detection) => Math.abs(d.y2 - d.y1) / d.frameHeight;
export function zoneFor(d: Detection): Zone {
  const ratio = centerXRatio(d);
  if (ratio < 1 / 3) return 'left';
  if (ratio > 2 / 3) return 'right';
  return 'center';
}
export function distanceBucketFor(d: Detection): DistanceBucket {
  const ratio = heightRatio(d);
  if (ratio > NEAR_RATIO) return 'near';
  if (ratio < FAR_RATIO) return 'far';
  return 'mid';
}
export function tierFor(zone: Zone, distance: DistanceBucket, approaching = false, approachingFast = false): Tier {
  if (distance === 'near') return zone === 'center' || approachingFast ? 'danger' : 'warning';
  if (distance === 'mid') return approaching ? 'warning' : 'notice';
  return 'silent';
}
export function utteranceFor(objClass: string, zone: Zone, tier: Tier): string {
  const name = objClass.replaceAll('_', ' ').trim() || 'object';
  const direction = zone === 'center' ? 'ahead' : zone;
  if (tier === 'danger') return `Stop - ${name} ${direction}`;
  if (tier === 'warning') return `${name} ${direction}`;
  if (tier === 'notice') return zone === 'center' ? `${name} ahead` : `${name} far ${zone}`;
  return '';
}
export function earconFor(zone: Zone, tier: Tier): string {
  if (tier === 'danger') return 'double_tone';
  if (tier === 'warning') return `panned_tone_${zone}`;
  return tier === 'notice' ? 'soft_cue' : '';
}

type TrackState = { lastSeenFrame: number; streak: number; announced: boolean; loggedTier: Tier | null; history: Array<[number, number]> };
const cloneEvent = (event: AlertEvent, changes: Partial<AlertEvent>): AlertEvent => ({ ...event, ...changes });

export class Triage {
  private tracks = new Map<number, TrackState>();
  private pendingDetections = new Map<number, Detection>();
  private queue: AlertEvent[] = [];
  private frame = -1;
  readonly log: AlertEvent[] = [];
  constructor(readonly persistFrames = PERSIST_FRAMES, readonly clearFrames = CLEAR_FRAMES) {}
  observe(detection: Detection): void { this.pendingDetections.set(detection.trackId, detection); }
  observeAll(detections: Detection[]): void { detections.forEach((d) => this.observe(d)); }
  emit(frameIndex?: number): AlertEvent[] {
    const frame = frameIndex ?? (this.pendingDetections.size ? Math.max(...[...this.pendingDetections.values()].map((d) => d.frameIndex)) : this.frame + 1);
    this.frame = frame;
    const detections = this.pendingDetections;
    this.pendingDetections = new Map();
    const candidates = [...detections.values()].map((d) => this.updateTrack(d));
    this.expireAbsent(frame);
    candidates.forEach((event) => { if (event) this.queue.push(event); });
    return this.drain();
  }
  private updateTrack(d: Detection): AlertEvent | null {
    let state = this.tracks.get(d.trackId);
    if (!state) { state = { lastSeenFrame: d.frameIndex, streak: 1, announced: false, loggedTier: null, history: [] }; this.tracks.set(d.trackId, state); }
    else if (d.frameIndex > state.lastSeenFrame) { state.streak = d.frameIndex === state.lastSeenFrame + 1 ? state.streak + 1 : 1; state.lastSeenFrame = d.frameIndex; }
    const ratio = heightRatio(d);
    let growth = 1;
    if (state.history.length >= 2) { const oldest = state.history[0]; if (oldest) { const [pastFrame, pastRatio] = oldest; const elapsed = d.frameIndex - pastFrame; if (elapsed > 0 && pastRatio > 0) growth = Math.pow(Math.pow(ratio / pastRatio, 1 / elapsed), APPROACH_WINDOW_FRAMES); } }
    state.history = [...state.history, [d.frameIndex, ratio] as [number, number]].slice(-APPROACH_WINDOW_FRAMES);
    const zone = zoneFor(d); const distance = distanceBucketFor(d); const approaching = growth >= APPROACH_GROWTH;
    const tier = tierFor(zone, distance, approaching, growth >= FAST_GROWTH);
    if (state.streak < this.persistFrames) return null;
    if (tier === 'silent') { if (state.loggedTier !== 'silent') { state.loggedTier = 'silent'; this.log.push(this.event(d, zone, distance, tier, approaching)); } return null; }
    if (state.announced || this.queue.some((e) => e.trackId === d.trackId)) return null;
    state.loggedTier = tier;
    return this.event(d, zone, distance, tier, approaching);
  }
  private event(d: Detection, zone: Zone, distance: DistanceBucket, tier: Tier, approaching: boolean): AlertEvent {
    return { frameIndex: d.frameIndex, spokenFrame: null, trackId: d.trackId, objClass: d.objClass, zone, distance, tier, approaching, utterance: utteranceFor(d.objClass, zone, tier), earcon: earconFor(zone, tier), maxLatencyMs: MAX_LATENCY_MS[tier] ?? null, spoken: false, preempted: false };
  }
  private expireAbsent(frame: number): void { for (const [id, state] of this.tracks) if (frame - state.lastSeenFrame >= this.clearFrames) { this.tracks.delete(id); this.queue = this.queue.filter((e) => e.trackId !== id); } }
  private drain(): AlertEvent[] {
    if (!this.queue.length) return [];
    const dangers = this.queue.filter((e) => e.tier === 'danger');
    if (dangers.length) { this.queue.filter((e) => e.tier !== 'danger').forEach((e) => this.log.push(cloneEvent(e, { preempted: true }))); this.queue = []; return this.speak(dangers); }
    const warnings = this.queue.filter((e) => e.tier === 'warning');
    if (warnings.length) { this.queue = this.queue.filter((e) => e.tier !== 'warning'); return this.speak(warnings); }
    const notices = [...this.queue]; this.queue = []; return this.speak(notices);
  }
  private speak(events: AlertEvent[]): AlertEvent[] { return events.map((event) => { const state = this.tracks.get(event.trackId); if (state) state.announced = true; const spoken = cloneEvent(event, { spoken: true, spokenFrame: this.frame }); this.log.push(spoken); return spoken; }); }
  get pending(): AlertEvent[] { return [...this.queue]; }
  trackedIds(): Set<number> { return new Set(this.tracks.keys()); }
}
