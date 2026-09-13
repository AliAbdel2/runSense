# PROGRESS

## Environment setup (pre-checkpoint 1)
- Flutter SDK not previously installed on this machine. Installed stable channel via `git clone` into `C:\flutter`, added to user PATH permanently.
- Run target chosen: **Chrome/web only** for this hackathon (no Android SDK/emulator installed — `flutter doctor` shows Android toolchain and Visual Studio (Windows desktop) as missing/red, this is expected and not needed).
- Project created at `Application/` (repo root has a stale, unrelated React Native/Expo scaffold under `mobile/` from before the pivot to Flutter — left untouched, not part of this app).
- Verified `flutter build web --release` succeeds end-to-end.
- Saved both planning docs into this folder: `runsense_flutter_plan.md` (this app) and `obstacle_detection_module_plan.md` (Phase 2, camera-based perception — built after this app's mocked skeleton is done). Added a section 10 note to `runsense_flutter_plan.md` cross-referencing how the obstacle-detection module will eventually become `LivePerceptionService`.

## Checkpoint 1 — Scaffold
- Added `provider ^6.1.2`, `flutter_tts ^4.2.0`, `intl ^0.19.0` to `pubspec.yaml`, ran `flutter pub get`.
- Created `lib/app_config.dart` with `useMock = true`.
- Created models exactly as specified in plan section 3:
  - `lib/models/athlete.dart` — `Athlete`
  - `lib/models/guide_status.dart` — `GuideStatus` enum (split out of `session.dart` per the plan's own folder listing in section 2)
  - `lib/models/session.dart` — `SessionType` enum, `PlannedSession`, `CompletedSession`
  - `lib/models/alert.dart` — `AlertTier`, `Zone`, `Distance` enums, `ObstacleAlert`
- Created abstract service interfaces exactly as specified in plan section 4:
  - `lib/services/plan_service.dart` — `PlanService`
  - `lib/services/session_service.dart` — `SessionService`
  - `lib/services/perception_service.dart` — `PerceptionService`
  - `lib/services/agent_chat_service.dart` — `AgentChatService`
- **Deviations from section 2's folder listing (flagged for whoever reads this next):**
  - Did **not** create `models/activity.dart` or `models/plan_week.dart`. Section 3 of the plan gives no code for either, and no interface in section 4 references them (`PlanService.getWeekPlan` returns `List<PlannedSession>` directly, not a wrapper). Skipped rather than inventing speculative fields. Add them in a later checkpoint only if a concrete need shows up (e.g. a `WeekPlan` wrapper if the mock/live plan services end up needing week-level metadata beyond a list).
  - Did **not** create `lib/services/tts_service.dart` yet. It's real (not mocked) per section 4, but the hour-by-hour breakdown (section 7) wires it up alongside the Home screen (hours 2–3.5), so it's deferred to that checkpoint rather than built with nothing to call it yet.
- No mock data, no mock service implementations, no UI/screens built yet — intentionally out of scope for Checkpoint 1.
- `flutter analyze` — no issues.

## Housekeeping (between checkpoints 1 and 2)
- Pulled `origin/main` (fast-forward, no conflicts): backend restructured from `runsense/` into an `app/` package. `Application/` was untracked so it rode through unaffected.
- Removed the stale `mobile/` React Native/Expo scaffold entirely (36 files) — the Flutter app in `Application/` replaces it, so it was dead weight. Committed as `51695b7`.
- Checked `app/models/{athlete,session,alert,activity,plan_week}.py` on the backend — currently empty placeholder files, so there was nothing yet to cross-check our Dart model field names against. Revisit once a teammate fills those in (plan section 3 says our models should mirror them).

## Checkpoint 2 — Mock data + mock services
- `lib/services/mock/mock_data.dart`: Sara persona (`MockData.athlete`), `baseWeek()` (Mon rest, Tue hard interval/guide accepted/track, Wed rest, Thu easy/no guide, Fri rest, Sat long run/guide accepted, Sun rest), `adaptedWeek()` (Tue flips to pending "guide cancelled", Thu extends to 7k to compensate — this is what `requestReplan()` swaps in), and `alertScript` (the exact t+2s/t+6s/t+9s NOTICE/WARNING/DANGER sequence from section 5, as a list of `ScriptedAlertCue` so it's editable in seconds before a demo).
- `lib/services/mock/mock_plan_service.dart`: `MockPlanService implements PlanService` — 300ms simulated delay, `requestReplan()` swaps in `MockData.adaptedWeek()`.
- `lib/services/mock/mock_perception_service.dart`: `MockPerceptionService implements PerceptionService` — broadcast `StreamController<ObstacleAlert>`, `startSimulation()` schedules one `Timer` per `alertScript` cue (cancels/resets any prior timers first), `stopSimulation()` cancels them. Added a non-interface `dispose()` to close the controller when the owning screen goes away.
- `lib/services/mock/mock_agent_chat_service.dart`: `MockAgentChatService implements AgentChatService` — keyword match on "plan"+"week", "guide", "cancel"/"replan", else an echo fallback.
- `lib/services/mock/mock_session_service.dart`: `MockSessionService implements SessionService`.
  - **Deviation, flagged:** section 5 says `endSession()` should "return one [a CompletedSession] with adaptationNote set," but the section 4 interface locks `endSession` to `Future<void>`. Rather than change the already-built contract, added a non-interface field `lastCompleted` that's populated when `endSession()` resolves (with `adaptationNote: 'Thu reduced because Tue was cut short'`). Whichever screen shows the post-run summary should read `(sessionService as MockSessionService).lastCompleted` for now — if a `LiveSessionService` needs this later, consider promoting a `completedSessions` stream onto the `SessionService` interface itself instead of this cast.
- `flutter pub get` + `flutter analyze` — no issues.

## Checkpoint 3 — Home screen
- `lib/services/tts_service.dart`: real (not mocked) wrapper around `flutter_tts` — `speak()`, `interruptAndSpeak()` (stops then speaks, for Live Run's DANGER-tier interrupts in checkpoint 4), `stop()`.
- `lib/widgets/big_action_button.dart`: shared >=64px button (`primary: true` = filled/ElevatedButton for the main action, `false` = outlined for secondary), always wrapped in `Semantics(button: true, label: ...)`.
- `lib/screens/home_screen.dart`: on `initState`, loads the week via `PlanService.getWeekPlan()`, picks the entry matching today's ISO date (falls back to the first entry if none match, so the demo never shows a blank screen), speaks `spokenSummary` via `TtsService`, wrapped in `Semantics(liveRegion: true)`. "START SESSION" button calls `SessionService.startSession()` + speaks a confirmation (navigation to Live Run is a checkpoint 6 concern — left as a TODO comment). "ASK COACH" simulates a recognized phrase (no speech-to-text package in this plan) and round-trips it through `AgentChatService`, speaking the reply.
  - **Decision, flagged:** disabled the Start Session button on rest days (`SessionType.rest`) — not explicitly specified in the plan, but starting a "session" on a rest day made no sense. Revisit if a teammate wants rest days to do something else (e.g. show stretching tips).
- `lib/main.dart`: rewritten from the default counter demo. Wires `MultiProvider` with `PlanService`/`SessionService`/`PerceptionService`/`AgentChatService` selected by `useMock` (throws `UnimplementedError` on the `false` branch until a `Live*Service` exists — intentional, so flipping the flag early fails loudly instead of silently doing nothing), plus a real `TtsService`. `home: const HomeScreen()`.
- `test/widget_test.dart`: replaced the stock counter test (referenced the now-deleted `MyApp`) with a smoke test that pumps `RunSenseApp`, waits out the mocked 300ms plan-load delay, and checks the app bar renders.
- `flutter analyze` — no issues. `flutter test` — passing.
- **Known web-target quirk:** running in Chrome, the console logs `[object SpeechSynthesisErrorEvent]` on the auto-announce — Chrome's Web Speech API can refuse to speak without a prior user gesture on the page. Not a code bug; native `flutter_tts` on a real device doesn't have this restriction. Re-verify speech actually plays once tested on a phone.

## Checkpoint 4 — Live Run screen
- `lib/screens/live_run_screen.dart`: `LiveRunScreen(plannedSessionId)`. On `initState`, calls `SessionService.startSession()` to obtain a `sessionId`, subscribes to `PerceptionService.alertStream()`, then calls `startSimulation()`. Each incoming alert is spoken via `TtsService.speak()`; `AlertTier.danger` instead calls `TtsService.interruptAndSpeak()` and `HapticFeedback.heavyImpact()` (from `flutter/services.dart` — no new package needed, it's built into the Flutter SDK). Zone indicator is the "simplified to a big colored panel + text" option from section 6.2, not the full LEFT/CENTER/RIGHT × NEAR/MID/FAR grid: color (grey=idle/all-clear, amber/orange/red by tier) + icon + tier/zone/distance text, so state is never color-only. Tracks `_alertCount` in-memory (incremented per alert) and shows it on screen — this is the "simple in-memory alert count for the end-of-session summary" the plan asks for; no separate summary screen exists yet to hand it to. "END SESSION" button stops the perception simulation, stops TTS, calls `SessionService.endSession(sessionId)`, then pops the route.
- `lib/screens/home_screen.dart`: **scope addition beyond checkpoint 4's stated task, flagged.** Wired a minimal `Navigator.push` from "START SESSION" to `LiveRunScreen` (replacing the old TODO comment) — needed a way to actually reach and manually test the new screen in Chrome. This is *not* the full checkpoint 6 nav (which also has to return to Home showing the adapted plan after `requestReplan()` — that needs the Week Plan screen from checkpoint 5 first, so it can't be done yet). Also moved the `SessionService.startSession()` call out of `_startSession()` and into `LiveRunScreen` itself, since `LiveRunScreen` needs the returned `sessionId` to later call `endSession()` — calling `startSession()` in both places would have started two sessions per run. `home_screen.dart` no longer imports `SessionService` as a result.
- No haptics/vibration package added — `HapticFeedback` is part of Flutter's own `services.dart`, sufficient for the DANGER-tier buzz the plan asks for.
- `flutter analyze` — no issues. `flutter test` — passing. `flutter build web --release` — succeeds (pre-existing `flutter_tts` wasm-dry-run lint warnings from the package itself, unrelated to this checkpoint's code, not treated as errors).
- **Verified live**: launched via `flutter run -d chrome`, user clicked through Home → Start Session → Live Run alert sequence → End Session in the browser and confirmed it works.

## Checkpoint 5 — Week Plan screen
- `lib/widgets/guide_status_chip.dart`: `GuideStatusChip(status)` — a `Chip` keyed off `GuideStatus` (accepted/pending/declined/notNeeded), each with its own color + icon + text label ("Guide confirmed" / "Guide pending" / "Guide declined" / "No guide needed") so state is never color-only.
- `lib/screens/week_plan_screen.dart`: `WeekPlanScreen` — loads the week via `PlanService.getWeekPlan('sara-1')` on `initState`, renders a read-only `ListView` (date · session type, one-sentence description, `GuideStatusChip`), each row ≥64px tall. Long-press on a row calls `PlanService.requestReplan('Guide cancelled: <description>')`, reloads the week (the mock service mutates its cached week in place, so a second `getWeekPlan()` call returns the adapted one), speaks "Your week has been updated." via TTS, and shows a confirmation snackbar. A full-screen dim + spinner guards against double-triggering a replan while one is in flight.
- `lib/screens/home_screen.dart`: added a `calendar_view_week` icon button to the app bar (64×64 touch target via `constraints`, wrapped in `Semantics(button: true)`) that pushes `WeekPlanScreen`. On return, Home reloads and re-announces today's session — this incidentally covers part of checkpoint 6's "back to Home showing the adapted plan after `requestReplan()`" goal, though the rest of checkpoint 6 (broader accessibility pass, confirming the full three-screen nav loop) is still open.
- `flutter analyze` — no issues (one `unnecessary_underscores` lint on `separatorBuilder`'s params, fixed by using single `_` for both). `flutter test` — passing.
- **Verified live**: relaunched `flutter run -d chrome`, confirmed the Week Plan screen loads and renders correctly. Long-press replan flow not yet clicked through in-browser by the user — do that alongside checkpoint 6.
- **Recurring dev-loop snag, not a code issue**: `flutter run -d chrome` twice failed with "Flutter failed to delete a directory at ...build\flutter_assets" — a leftover Chrome tab/process holds a lock on the previous build's assets. Fix each time is `Remove-Item -Recurse -Force build` before relaunching. Worth remembering if this trips up the next checkpoint's manual verification too.

**Next checkpoint (6):** accessibility + nav pass (plan section 6, checkpoint 6) — confirm Semantics/live-region announcements and 64px touch targets across all three screens, and firm up the Home → Live Run → Home and Home → Week Plan → Home nav loop (including showing the adapted plan after a replan, already partly working per above).
