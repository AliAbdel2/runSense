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

**Next checkpoint (4):** build the Live Run screen (plan section 6.2) — zone indicator, subscribe to `PerceptionService.alertStream()`, speak alerts via `TtsService.interruptAndSpeak()` for DANGER tier, haptic feedback.
