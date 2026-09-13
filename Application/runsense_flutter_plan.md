# RunSense — Flutter Mobile App: 8-Hour Build Plan

Your scope: the **Mobile App (React Native → we're using Flutter)** box from the architecture doc — Home/Today, Live Run, Week Plan. Voice-first, TalkBack/VoiceOver-friendly, all data mocked but shaped exactly like what the backend/perception teammates will eventually send, so wiring in real data later is a one-line swap, not a rewrite.

## 0. Guiding rule

**Never hardcode data inside a widget.** Every screen reads from a `Provider`-exposed service that implements an abstract interface. Today that interface is backed by a `Mock*` class returning canned/simulated data. Later, someone swaps in a `Live*` class hitting the real WebSocket/REST/Strava/Calendar APIs — same interface, zero UI changes.

```
UI widgets
   ↓ (Provider)
Abstract service interfaces  ← THE CONTRACT
   ↓
MockXService (today, hour 0-8)   |   LiveXService (post-hackathon / if time allows)
```

---

## 1. Packages

```yaml
dependencies:
  flutter:
    sdk: flutter
  provider: ^6.1.2
  flutter_tts: ^4.2.0
  intl: ^0.19.0
```

Keep it lean — no networking package needed since nothing is live yet. Add `web_socket_channel` and `http` later only when a teammate's endpoint is actually ready.

---

## 2. Folder structure

```
lib/
  main.dart
  models/
    athlete.dart
    activity.dart
    plan_week.dart
    session.dart          // a single planned/actual run
    alert.dart            // perception alert (zone/tier/utterance)
    guide_status.dart     // enum: pending/accepted/declined
  services/
    plan_service.dart          // abstract PlanService
    session_service.dart       // abstract SessionService
    perception_service.dart    // abstract PerceptionService (alert stream)
    agent_chat_service.dart    // abstract AgentChatService (push-to-talk)
    tts_service.dart           // real, not mocked
    mock/
      mock_plan_service.dart
      mock_session_service.dart
      mock_perception_service.dart
      mock_agent_chat_service.dart
      mock_data.dart          // the canned JSON-shaped Dart objects (Sara persona)
  screens/
    home_screen.dart
    live_run_screen.dart
    week_plan_screen.dart
  widgets/
    session_card.dart
    zone_indicator.dart
    guide_status_chip.dart
    big_action_button.dart   // the 64px+ primary button pattern used on all 3 screens
  app_config.dart            // useMock = true/false lives here, nowhere else
```

---

## 3. Data models (mirror the backend's Postgres tables from section 10 — same field names)

```dart
// athlete.dart
class Athlete {
  final String id, name;
  final List<String> guideDays;      // e.g. ["Tue", "Sat"]
  final String preferredVenue;       // "track" | "treadmill" | "outdoor"
}

// session.dart
enum SessionType { easy, hard, longRun, rest }
enum GuideStatus { pending, accepted, declined, notNeeded }

class PlannedSession {
  final String id, date;             // ISO date
  final SessionType type;
  final String description;          // e.g. "4x800m intervals"
  final String spokenSummary;        // <25 words, TTS-ready — matches doc's hard rule
  final GuideStatus guideStatus;
  final String venue;
}

class CompletedSession {
  final String sessionId;
  final double actualKm;
  final Duration duration;
  final int alertCount;
  final String? adaptationNote;      // "Thu reduced because Tue was cut short"
}

// alert.dart
enum AlertTier { danger, warning, notice }
enum Zone { left, center, right }
enum Distance { near, mid, far }

class ObstacleAlert {
  final String objectClass;          // "person", "bicycle", ...
  final Zone zone;
  final Distance distance;
  final AlertTier tier;
  final String utterance;            // "Stop - person ahead"
  final int latencyMs;
  final DateTime ts;
}
```

These field names should match section 10 of the plan doc closely enough that whoever wires the real WebSocket later just deserializes into the same classes.

---

## 4. Service interfaces (the contract)

```dart
abstract class PlanService {
  Future<List<PlannedSession>> getWeekPlan(String athleteId);
  Future<void> requestReplan(String reason); // "guide cancelled" etc.
}

abstract class SessionService {
  Future<CompletedSession> startSession(String plannedSessionId);
  Future<void> endSession(String sessionId);
}

abstract class PerceptionService {
  Stream<ObstacleAlert> alertStream();   // starts/stops with session
  void startSimulation();
  void stopSimulation();
}

abstract class AgentChatService {
  Future<String> sendMessage(String text); // "Plan my week, guide only Tue/Sat"
}
```

`TtsService` is NOT abstract/mocked — build it for real with `flutter_tts` from the start. It's the one piece of the stack that's genuinely free to make real in Flutter and it's central to the demo.

---

## 5. Mock implementations — what each one actually does

- **MockPlanService**: returns a hardcoded week for "Sara" — Tue hard interval (guide accepted, track), Thu easy, Sat long run with guide, rest days — with `Future.delayed(300ms)` to simulate a network round trip. `requestReplan()` swaps in a pre-built "adapted" week and returns it, so the demo's adaptation beat (section 14, 3:10–3:50) works without a real LLM call.
- **MockSessionService**: `startSession` returns a `CompletedSession` stub; `endSession` after a delay returns one with `adaptationNote` set, to simulate the "verify upload → rewrite Thursday" moment.
- **MockPerceptionService**: this is the one worth doing carefully — it's your live-run centerpiece. Use a `Timer.periodic` or a scripted `Stream` that emits a **fixed sequence** timed to match the demo script exactly:
  - t+2s: NOTICE, "bike far right"
  - t+6s: WARNING, zone=left, "person left"
  - t+9s: DANGER, zone=center, near, "Stop - person ahead" (this one should also trigger haptic + interrupt any current TTS)
  - Then silence, so the demo has breathing room.
  Make the sequence configurable (a list you can edit in 10 seconds before the actual demo run).
- **MockAgentChatService**: pattern-match on keywords in the input ("plan my week" → canned plan-created response mentioning Strava pull + Calendar invite) so the push-to-talk screen feels alive without an LLM call.

Put all the canned data in one `mock_data.dart` so it's obvious where to look and edit before the demo.

---

## 6. Screens (from section 9 of the doc — build in this order)

1. **Home/Today** — speaks today's session on open (`spokenSummary` → `flutter_tts`), one big "Start session" button (≥64px), secondary "Ask coach" push-to-talk button. Auto-announce via `Semantics(liveRegion: true)`.
2. **Live Run** — large zone indicator (LEFT/CENTER/RIGHT × NEAR/MID/FAR grid, or simplified to a big colored panel + text), last alert text, listens to `PerceptionService.alertStream()`, speaks each alert via TTS (DANGER interrupts current speech — `flutter_tts.stop()` then `speak()`), logs a simple in-memory alert count for the end-of-session summary.
3. **Week Plan** — read-only list of `PlannedSession`s, one sentence each, `GuideStatusChip` (accepted/pending/declined), long-press → calls `requestReplan()`.

Accessibility, since it's core to the pitch, not a nice-to-have: 64px touch targets everywhere, no color-only state (icon + text + color), screen-reader focus order matches spoken order, test with TalkBack/VoiceOver at least once before the demo.

---

## 7. Hour-by-hour (8 hours)

| Hours | Task |
|---|---|
| 0–1 | `flutter create`, folder scaffold, models, service interfaces, `app_config.dart` with `useMock=true`, add packages |
| 1–2 | Mock services + `mock_data.dart` (Sara persona, scripted alert sequence) |
| 2–3.5 | Home screen + `flutter_tts` wired and speaking on open |
| 3.5–5 | Live Run screen: alert stream UI, zone indicator, TTS interrupt logic for DANGER, haptics |
| 5–6 | Week Plan screen + replan flow |
| 6–7 | Accessibility pass (Semantics, touch targets, screen-reader test) + visual polish |
| 7–7.5 | Wire the three screens into one nav flow (Home → Live Run → back to Home showing adapted plan) |
| 7.5–8 | Buffer: rehearse against the demo script (section 14) with the scripted alert timing, fix whatever breaks |

---

## 8. Checkpointed workflow for Claude Code — fresh session per checkpoint

Each checkpoint below is a **new Claude Code session**, not a continuation. That means Claude Code has no memory of decisions made in the last session — it only knows what's on disk. So two things have to live in the repo, not in chat history:

1. **This plan file itself** — keep `runsense_flutter_plan.md` at the project root the whole time. Every prompt below tells Claude Code to read it first.
2. **A running `PROGRESS.md`** — after each checkpoint you approve, have Claude Code (still in that same session, before it ends) append 3-5 lines to `PROGRESS.md`: what it built, any naming/convention decisions it made that weren't in the plan (e.g. "used `Provider.of` not `Consumer` for X"), and anything you told it to change. This is what keeps the next fresh session consistent — not its memory, the file.

Every checkpoint prompt should open with something like:

> Read `runsense_flutter_plan.md` and `PROGRESS.md` in this repo, and look at the current `lib/` folder, before doing anything. Then: [task]. When you're done, append a short summary to `PROGRESS.md`. Stop there — don't start the next section.

**Checkpoint 1 — Scaffold**
> [orientation line above] + Set up the Flutter project with the folder structure in section 2. Create the model classes in `models/` (section 3) and the abstract service interfaces in `services/` (section 4). Don't implement anything yet — no mock data, no UI.

**Checkpoint 2 — Mock data + mock services**
> [orientation line] + Implement `mock/mock_data.dart` with a Sara persona (Tue hard interval w/ guide accepted on track, Thu easy, Sat long run w/ guide, rest days) and the four Mock*Service classes (section 5), including the scripted alert sequence with exact timings (t+2s NOTICE, t+6s WARNING, t+9s DANGER). Wire `app_config.dart` with `useMock=true`. No screens yet.

**Checkpoint 3 — Home screen**
> [orientation line] + Build the Home/Today screen (section 6.1): speaks today's session on open via flutter_tts, big Start Session button (≥64px), secondary Ask Coach button. Pull data through Provider from the mocked PlanService.

**Checkpoint 4 — Live Run screen**
> [orientation line] + Build the Live Run screen (section 6.2): zone indicator, listens to PerceptionService.alertStream(), speaks alerts via TTS, DANGER interrupts current speech + haptic.

**Checkpoint 5 — Week Plan screen**
> [orientation line] + Build the Week Plan screen (section 6.3): session list, GuideStatusChip, long-press → requestReplan().

**Checkpoint 6 — Accessibility + nav**
> [orientation line] + Add Semantics/live-region announcements, confirm 64px touch targets, wire navigation Home → Live Run → back to Home showing the adapted plan after requestReplan().

**Checkpoint 7 — Rehearsal fixes**
> Only after you've personally run through the demo script and found issues — hand the fresh session the specific bugs/tweaks, not "polish everything." Still start with the orientation line so it doesn't reinvent something already working.

At each stop: **actually run `flutter run` yourself before approving** — a checkpoint that compiles but crashes on first launch costs more time to catch three sessions later, and with fresh sessions there's no "wait, why did you do it this way" thread to pull on.

## 9. What this buys the team at integration time

When perception/agent/backend teammates are ready, they each replace exactly one file:

- Real WebSocket alerts → new `LivePerceptionService implements PerceptionService`
- Real Strava/Calendar/LLM → new `LivePlanService`, `LiveAgentChatService`
- Flip `useMock = false` in `app_config.dart`, rebuild.

No screen code changes. That's the whole point of building it this way under time pressure — you're not blocked on anyone, and nobody's blocked on you re-architecting later.

---

## 10. Phase 2 note — obstacle detection module

A separate doc (`obstacle_detection_module_plan.md`, kept alongside this one) specs a camera + ML Kit based real-time obstacle detector (`ObstacleDetectionController`, `DetectionService`, `FeedbackService`, etc. under `lib/features/obstacle_detection/`). That module is Phase 2, built after this app's mocked skeleton (Checkpoints 1-7 above) is done.

Integration point: that module's own `DetectedObstacle`/`ObstacleAlert` types (direction/urgency/trackingId) are its internal pipeline representation, not the same class as this plan's `models/alert.dart` `ObstacleAlert` (objectClass/zone/distance/tier/utterance). When Phase 2 lands, it becomes the body of a `LivePerceptionService implements PerceptionService` — translating its internal alerts into this app's `ObstacleAlert` shape at the boundary, and emitting them on `alertStream()`. No changes needed to Live Run screen or any other screen code for that swap to happen — that's the reason the interface exists.
