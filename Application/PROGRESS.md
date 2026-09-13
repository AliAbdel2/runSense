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

## Checkpoint 6 — Accessibility + nav
- `lib/screens/home_screen.dart`: `_startSession()` now also reloads (`_loadAndAnnounce()`) after the Live Run push returns, mirroring what `_openWeekPlan()` already did — so both nav paths (Home → Live Run → Home, Home → Week Plan → Home) refresh and re-speak today's session on return, closing out the "back to Home showing the adapted plan" goal for both loops. The coach's reply `Text` is now wrapped in `Semantics(liveRegion: true)` so a screen reader announces it automatically when it appears, not just visually.
- `lib/screens/week_plan_screen.dart`: added a `customSemanticsActions` entry ("Request replan") alongside the existing long-press `Semantics` label on each row. Reasoning: a bare long-press gesture is genuinely hard to trigger through TalkBack/VoiceOver's own gesture layer (their default single-tap activates the accessibility focus action, not the underlying `onLongPress`), so a custom action is the standard Flutter way to expose that same action to a screen reader — this is a real accessibility fix, not just polish. Needed `import 'package:flutter/semantics.dart'` for `CustomSemanticsAction`.
- `lib/widgets/accessible_back_button.dart` (new): a 64×64 `Semantics(button: true)`-wrapped back arrow, because Material's default `AppBar` back button is only 48px and the plan's touch-target rule says "everywhere." Used as `WeekPlanScreen`'s `leading`.
  - **Deviation, flagged:** did *not* use this shared widget on `LiveRunScreen`. Its back arrow needs to run the same cleanup as "END SESSION" (stop the perception simulation, stop TTS, call `SessionService.endSession()`) rather than a bare `Navigator.pop()`, so it has its own inline 64×64 `IconButton` wired to `_endSession` instead. Otherwise leaving Live Run via the back arrow would silently skip ending the session.
- Audited touch targets across all three screens: `BigActionButton` (72/64px), Home's app-bar calendar icon (64px, from checkpoint 5), the two back buttons above, and Week Plan's row `Container`s (`minHeight: 64`) are all compliant. Left `SnackBar`'s own dismiss affordance and `Chip`'s internal hit area alone — both are framework chrome, not custom interactive elements the plan's rule is aimed at.
- `flutter analyze` — no issues (`flutter/semantics.dart` import needed for `CustomSemanticsAction`, otherwise it isn't resolved as a class). `flutter test` — passing.
- **Verified live**: relaunched `flutter run -d chrome`; app boots cleanly with no new console errors beyond the known `SpeechSynthesisErrorEvent` quirk. Full click-through of the refreshed Home ↔ Live Run and Home ↔ Week Plan loops, plus an actual TalkBack/VoiceOver pass per the plan's own accessibility rule, still needs a human — Chrome DevTools' screen-reader emulation isn't a substitute and there's no accessibility-tree inspection tool available in this session.
- Not yet done from the plan's checkpoint 6 wording: a dedicated end-of-session summary UI to actually display `LiveRunScreen`'s `_alertCount` / `MockSessionService.lastCompleted.adaptationNote` — the plan only asked for the *data* to be tracked (done, checkpoint 4), not a summary screen; flagging in case that's expected to exist before a demo.

**Next checkpoint (7):** rehearsal fixes — only after manually running the full demo script (plan section 14) end-to-end and finding concrete issues, per the plan's own instruction not to "polish everything" speculatively.

## Out-of-band — GPS/permission groundwork (not a numbered checkpoint)
User asked to keep camera access, GPS access, and TTS in mind going forward. Clarified scope before touching anything: camera-based obstacle detection (`obstacle_detection_module_plan.md`) is being built by a **teammate**, and neither camera nor GPS work on Flutter web (this machine only has the web toolchain — no Android SDK/emulator, per the checkpoint-1 note), so nothing here could be live-verified beyond `flutter analyze`/`flutter test`/booting in Chrome. Scoped to **interfaces + permission plumbing only**, `useMock` stays `true`:
- `android/app/src/main/AndroidManifest.xml`: added `CAMERA`, `VIBRATE`, `ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION` permissions + the camera `<uses-feature>`, matching `obstacle_detection_module_plan.md` section 4.1 exactly (camera side is there for the teammate's benefit, even though I'm not writing that code). **No `ios/` directory exists in this project** (Windows machine, no Xcode) — the plan's iOS `Info.plist` usage-description keys (section 4.2) can't be added until someone runs `flutter create --platforms=ios .` from a Mac.
- `pubspec.yaml`: added `geolocator ^13.0.2` and `permission_handler ^11.3.1`. Deliberately did **not** add `camera` or any `google_mlkit_*` package — that's the teammate's dependency choice to make when they build the obstacle detection module themselves; adding it now risked picking a version or config that conflicts with their setup.
- `lib/models/location_fix.dart` (new): `LocationFix` (lat/lon/speed/timestamp) — our own small model, same reasoning as `ObstacleAlert` not being a raw ML Kit type: screens should never depend on `geolocator`'s `Position` type directly.
- `lib/services/location_service.dart` (new): `LocationService` abstract interface — `requestPermission()`, `positionStream()`, `startTracking()`/`stopTracking()`. **Not in the original plan's section 4** (that doc never mentioned GPS) — designed fresh, mirroring `PerceptionService`'s stream + start/stop shape since that pattern already fit the "external hardware feed" use case.
- `lib/services/mock/mock_location_service.dart` (new): `MockLocationService` — emits a fake, gently-drifting lat/lon once a second via `Timer.periodic`, so anything wired to `LocationService` later (pace/distance on Live Run, an end-of-session summary) has something to render before a real GPS integration exists.
- `lib/main.dart`: wired `Provider<LocationService>` the same way as the other four services (`useMock ? MockLocationService() : throw UnimplementedError(...)`).
- **Not done, deliberately**: no screen reads from `LocationService` yet — nothing asked for pace/distance UI, so this is pure plumbing, not a feature. No real `LiveLocationService` either (would need `geolocator`'s actual permission-request/position-stream calls) — that's real device-dependent work, same "needs a physical device to verify" situation as the obstacle detection module.
- `flutter pub get` pulled in `geolocator_web` (has a web backend, unlike camera/ML Kit) alongside the Android/iOS/Windows platform packages. `flutter analyze` — no issues. `flutter test` — passing. `flutter run -d chrome` — boots cleanly with the new provider wired in, no new console errors.

## Phase 2 — Obstacle detection module (camera + ML Kit)

Built `obstacle_detection_module_plan.md` Phase 1 (the MVP). Full write-up of
what changed and why is in **`../summary.md`**; device test plan is in
**`../testing/OBSTACLE-DETECTION-phase1/testing-guide.md`**. Both live at the
repo root so one task keeps its artifacts in one place.

- **Environment:** Flutter was not installed on this Mac (the earlier notes in
  this file describe a Windows machine). Installed stable **3.47.4 / Dart 3.13.3**
  to `~/development/flutter`. Android SDK already present at
  `~/Library/Android/sdk`. **Full Xcode and CocoaPods are still missing** — only
  Command Line Tools — so nothing iOS has been built.
- **New:** `lib/features/obstacle_detection/` — models, `CameraService`,
  `InputImageConverter`, `DetectionService`, `FeedbackService`,
  `ObstacleDetectionController`, `ObstacleDetectionScreen`, plus
  `LivePerceptionService` (the `PerceptionService` implementation this plan's
  section 10 anticipated) and a three-file conditional-import entry point.
- **Modified:** `pubspec.yaml` (camera, ML Kit, vibration, permission_handler),
  `main.dart` (TtsService moved to the top of the provider list, live perception
  wired behind `useMock`, `/obstacle-detection` route), `home_screen.dart` (a
  third button), Android manifest + `build.gradle.kts`.
- **Deviations from the module plan (all argued in `summary.md` §4):** shared the
  existing `TtsService` instead of a second `FlutterTts`; high-urgency alerts
  repeat on a 700 ms cadence rather than every analysed frame; the whole module
  sits behind a `dart:io` conditional import so the Chrome demo build keeps
  working; reused `BigActionButton`; added lifecycle/error/re-entrancy handling
  the plan omits.
- **Verified:** `flutter analyze` (no issues), `flutter test` (passing),
  `flutter build apk --debug` (succeeds), `flutter build web --release`
  (succeeds). Both sides of the platform guard checked in the built output: the
  web bundle contains the stub and none of the pipeline, the APK ships
  `libmlkitcommonpipeline.so` for all three ABIs.
- **Dependency gotcha, read `../summary.md` §7 before touching `pubspec.yaml`:**
  the module plan's pinned versions don't build (plugins on `compileSdk 33` are a
  hard error under AGP 9.1.0), but neither does simply taking latest —
  `permission_handler` 13.x wants SDK 37, which AGP 9.1.0 can't resolve. It is
  pinned at ^11.3.1 deliberately, with the reason written next to the pin.
- **NOT verified:** nothing has run on a phone. Every claim about escalation,
  direction, throttling and haptics is by construction. iOS is entirely unbuilt.
  The four tuning constants in `obstacle_detection_controller.dart` are
  guesses — plan §13 step 10 exists to replace them with measured values.

**Post-merge with `main` (checkpoints 4-6 + GPS groundwork):** `LiveRunScreen`
now exists and is exactly the consumer `LivePerceptionService` was written for —
it subscribes to `PerceptionService.alertStream()` and calls `startSimulation()`.
Two things to settle before `useMock` is flipped to `false`:
- `LiveRunScreen` and `ObstacleDetectionScreen` each construct their own
  `ObstacleDetectionController`, so each owns a `CameraService`. Opening both
  means two `CameraController`s on one device — the second throws. The
  `LivePerceptionService.controller` getter exists so the screen can share the
  one instance; wire that up rather than letting both create one.
- `Provider<PerceptionService>` in `main.dart` has no `dispose:` callback, so
  `LivePerceptionService.dispose()` never runs and the camera/detector leak on
  teardown.

Also fixed post-review in this branch: ML Kit bounding boxes are measured in the
rotated (upright) frame, so `InputImageConverter` now returns that size
(`ConvertedFrame`) and the proximity/direction ratios use it — previously they
divided by the raw frame dimensions, which on a portrait phone inflated every
obstacle to DANGER and skewed direction left. `stop()` now releases the camera
instead of only stopping the stream. `TtsService` no longer latches
`isSpeaking` forever if a completion callback is dropped (that would have
silenced every later alert), and `FeedbackService.dispose()` no longer stops the
app-wide TTS engine.
