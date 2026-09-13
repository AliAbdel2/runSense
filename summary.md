# Summary — Obstacle Detection module, Phase 1

**What:** Implements `Application/obstacle_detection_module_plan.md` (Phase 1 MVP)
— real-time camera-based obstacle detection with spoken + haptic feedback for
blind and low-vision runners.
**Where:** `Application/lib/features/obstacle_detection/`, plus wiring in
`main.dart`, `home_screen.dart`, `pubspec.yaml`, and the Android config.
**Testing:** `testing/OBSTACLE-DETECTION-phase1/testing-guide.md`.

---

## 1. The pipeline, as built

```
CameraService            rear camera, ResolutionPreset.medium, nv21/bgra8888
   -> InputImageConverter   CameraImage -> ML Kit InputImage (rotation + format)
   -> DetectionService      ML Kit object detector, stream mode + tracking
   -> _pickMostThreatening  proximity heuristic: tallest box wins
   -> _toAlert              proximity -> low / medium / high urgency
   -> _shouldFire           throttling, so we don't re-alert every frame
   -> FeedbackService       speech + vibration, escalating with urgency
```

All of it is orchestrated by `ObstacleDetectionController`, which is where every
policy decision lives (the two frame throttles, the heuristic thresholds, the
re-alert rules).

## 2. Files added

| File | Role | Plan § |
|---|---|---|
| `models/detected_obstacle.dart` | `ObstacleDirection`, `DetectedObstacle` | §6.4 |
| `models/obstacle_alert.dart` | `AlertUrgency`, module-internal `ObstacleAlert` | §6.4 |
| `services/camera_service.dart` | owns the camera + frame stream | §6.1 |
| `services/input_image_converter.dart` | `CameraImage` → ML Kit `InputImage` | §6.2 |
| `services/detection_service.dart` | ML Kit `ObjectDetector` wrapper | §6.3 |
| `services/feedback_service.dart` | speech + vibration | §7 |
| `obstacle_detection_controller.dart` | orchestration + all policy | §8 |
| `obstacle_detection_screen.dart` | the accessible UI | §9 |
| `live_perception_service.dart` | adapter onto the app's `PerceptionService` | app plan §10 |
| `obstacle_detection_entry.dart` + `_io` / `_stub` | platform guard (see §4) | — |

## 3. Files modified

| File | Change |
|---|---|
| `Application/pubspec.yaml` | added `camera`, `google_mlkit_object_detection`, `google_mlkit_commons`, `vibration`, `permission_handler` |
| `Application/lib/main.dart` | moved `TtsService` to the top of the provider list; `PerceptionService` now builds `LivePerceptionService` when `useMock` is false; registered the `/obstacle-detection` route |
| `Application/lib/screens/home_screen.dart` | third button, "OBSTACLE DETECTION", shown only where the feature can run |
| `Application/android/app/src/main/AndroidManifest.xml` | `CAMERA` + `VIBRATE` permissions, camera hardware feature |
| `Application/android/app/build.gradle.kts` | `minSdk = maxOf(flutter.minSdkVersion, 21)` |

## 4. Decisions that deviate from the plan (and why)

### 4.1 Platform guard so the web build keeps working — NEW

`PROGRESS.md` records that this app's demo target is Chrome. `google_mlkit_commons`
and the plan's own §6.1/§6.2 code import `dart:io`, which is a **compile error**
on web, not a runtime one. A single import chain from `main.dart` into this
module would therefore have broken `flutter build web` — silently killing the
demo path the team is actually rehearsing on.

So nothing imports the module directly. Everything goes through
`obstacle_detection_entry.dart`, a conditional export that resolves to the real
implementation where `dart:io` exists and to inert stubs on web. `main.dart` and
`home_screen.dart` only ever see `obstacleDetectionSupported`,
`obstacleDetectionRoute`, `buildObstacleDetectionScreen`, and
`createLivePerceptionService`.

Verified: `flutter build web --release` succeeds, and the compiled bundle
contains the stub's text but none of the camera pipeline's.

### 4.2 `FeedbackService` reuses the app's `TtsService` — CHANGED

The plan's §7 constructs its own `FlutterTts`. The app already has one in
`lib/services/tts_service.dart`, provided app-wide. Two engines would talk over
each other the moment a Live Run alert and an obstacle alert coincide — which is
exactly the scenario this module exists for. `FeedbackService` now takes the
shared `TtsService` by constructor and uses its existing `isSpeaking` flag for
the plan's "never talk over yourself" rule.

### 4.3 High-urgency alerts repeat on a cadence, not every frame — CHANGED

The plan's §8 `_shouldFire` returns `true` unconditionally for high urgency.
With frames analysed every 150 ms that fires a 400 ms vibration roughly seven
times a second — each one cancelling the last, so the net effect is a continuous
undifferentiated buzz, and the speech guard swallows most of the words.

Added `_highRepeatGap = 700ms`. It still "always warns" while something is that
close, just at a cadence a person can parse. **This is a tuning constant, not a
principle — raise or lower it during field testing.**

### 4.4 `TtsService` moved to the top of the provider list — REQUIRED

`MultiProvider` nests providers in list order, so a provider can only `read` the
ones declared *above* it. `PerceptionService` now reads `TtsService` during
creation, and `TtsService` was last in the list (`main.dart:47`) — it had to move
first or `createLivePerceptionService` would throw on lookup.

### 4.5 Small model additions — EXTENDED

- `DetectedObstacle.label` / `ObstacleAlert.label`: ML Kit already returns coarse
  labels (`classifyObjects: true` was in the plan), and the app's
  `lib/models/alert.dart` `ObstacleAlert` **requires** an `objectClass`. Without
  carrying the label through, every translated alert would have said "obstacle".
- `ObstacleAlert.latencyMs`: likewise required by the app's model. Measured in
  the controller as frame-received → alert-ready.

### 4.6 UI reuses `BigActionButton` — CHANGED

The plan's §9 hand-rolls an 88px `ElevatedButton`. The app already has
`lib/widgets/big_action_button.dart` — ≥72px, full width, always wrapped in
`Semantics`. Used that instead, so this screen stays consistent with Home if the
shared button is ever restyled.

### 4.7 Robustness not in the plan — ADDED

- **Lifecycle handling.** Streaming camera frames while backgrounded crashes the
  camera plugin on both platforms. The screen observes `didChangeAppLifecycleState`
  and stops on anything other than `resumed`.
- **`start()` failure path.** The plan's `start()` has no error handling; a
  camera that won't open would throw into the button's `onPressed`. It now
  catches, speaks "Could not start the camera", and surfaces the message on
  screen.
- **Tracking-id map pruning.** `_lastAlertPerObject` grew unbounded over a run.
  Entries older than 30 s are dropped once the map passes 200 entries.
- **Re-entrancy guards** on `start()` / `startStream()` so a double-tap can't
  open two camera sessions.

## 5. The integration seam (`LivePerceptionService`)

`runsense_flutter_plan.md` §10 specifies that this module keeps its own internal
alert types and translates at the boundary. That is what
`live_perception_service.dart` does:

| module | → | `lib/models/alert.dart` |
|---|---|---|
| `ObstacleDirection.left/center/right` | → | `Zone.left/center/right` |
| `AlertUrgency.high` | → | `AlertTier.danger` + `Distance.near` |
| `AlertUrgency.medium` | → | `AlertTier.warning` + `Distance.mid` |
| `AlertUrgency.low` | → | `AlertTier.notice` + `Distance.far` |
| `label` | → | `objectClass` |
| `latencyMs` | → | `latencyMs` |

Utterances match the phrasing already in `MockData.alertScript`
("Bike far right" / "Person left" / "Stop - person ahead"), so the demo sounds
identical whichever service is driving it.

The controller is constructed with `speakAlerts: false` in this path — when the
Live Run screen owns the speech, the module must stay quiet or every obstacle
gets announced twice.

**Not yet active.** `useMock` is still `true` in `lib/app_config.dart`, and the
Live Run screen this would feed is checkpoint 4 of `runsense_flutter_plan.md`,
which doesn't exist yet. The seam is wired and compiles; flipping the flag is a
separate decision for whoever builds that screen.

## 6. What was verified, and what wasn't

**Verified on this machine** (Flutter 3.47.4 / Dart 3.13.3, installed as part of
this task — it wasn't present):

- `flutter analyze` — **no issues**
- `flutter test` — existing smoke test passes
- `flutter build apk --debug` — **succeeds** (203 MB debug APK). Took three
  attempts; the two failures were dependency-version problems, not code — see §7
- `flutter build web --release` — **succeeds**

Both halves of the platform guard were checked empirically rather than assumed:

| | web bundle | Android APK |
|---|---|---|
| stub screen text | present | — |
| `'Obstacle detection on'` (real pipeline) | **absent** | — |
| `libmlkitcommonpipeline.so` | — | **present**, all three ABIs |

So the web build genuinely compiles the inert stub, and the Android build
genuinely ships the ML Kit native libraries.

**Not verified — no hardware, and stated plainly rather than glossed:**

- **Nothing has run on a phone.** The APK compiles and links; it has never been
  installed. Every behavioural claim in this document about escalation,
  direction, throttling, and haptics is *by construction*, not by observation.
  The whole of `testing-guide.md` §3–§9 is still outstanding.
- **iOS is entirely unbuilt.** `Application/ios/` did not exist; it was generated
  as part of this change (bundle id `com.runsense.runsense`, matching Android)
  and `NSCameraUsageDescription` was added to `ios/Runner/Info.plist` per plan
  §4.3, with `plutil -lint` confirming the plist is valid. Nothing beyond that:
  full Xcode is not installed on this Mac (only Command Line Tools) and
  CocoaPods is absent, so no iOS compile has happened.
  - Plan §4.4 turns out not to apply as written — there is no `ios/Podfile` yet
    (Flutter writes it on first `pod install`), and the setting that actually
    governs the floor, `IPHONEOS_DEPLOYMENT_TARGET`, is **already 15.0** in the
    generated Xcode project. §4.4's goal is met by default.
  - `permission_handler` needs a `PERMISSION_CAMERA=1` macro in the Podfile's
    `post_install` once that file exists, or it compiles in every permission
    handler and draws App Store review complaints.
- **The four tuning constants are guesses.** `_minFrameGap`, `_reAlertGap`,
  `_highRepeatGap`, and the `_proximity*` thresholds came from the plan or from
  reasoning, not from watching a real obstacle approach a real camera. Plan §13
  step 10 exists for this.

## 7. Dependency versions — newer is not simply better here

The plan's §3 pins resolve fine but **do not build for Android** on this
project's toolchain. Two separate walls, in both directions.

### Wall 1 — plugins compiled against android-33 are now a hard error

`flutter build apk --debug` failed with fifteen errors shaped like:

```
Dependency 'androidx.exifinterface:exifinterface:1.4.1' requires libraries and
applications that depend on it to compile against version 34 or later of the
Android APIs.
    :vibration is currently compiled against android-33.
```

The app's own `compileSdk` is fine (it inherits Flutter's). It's the **plugin
modules** that were stale — `vibration 2.1.0` declares `compileSdk 33`. Under the
AGP 9.1.0 / Gradle 9.3.1 this project pins in `android/settings.gradle.kts:19`,
that is an error rather than the warning it used to be.

### Wall 2 — but the newest plugins want an SDK this AGP can't read

Upgrading everything to latest replaced that failure with a different one:

```
Could not determine the dependencies of task
  ':permission_handler_android:compileDebugJavaWithJavac'.
> Failed to find target with hash string 'android-37' in: ~/Library/Android/sdk
```

`permission_handler 13.0.2` pulls `permission_handler_android 14.1.0`, which
declares `compileSdk = 37`. Gradle dutifully auto-installed that platform — but
it lands as `android-37.0` reporting `AndroidVersion.ApiLevel=37.0` (Android's
new minor-versioned SDK scheme), and AGP 9.1.0 looks up the integer hash
`android-37`. It cannot see it.

### Where each package landed, and why

| package | plan | now | why |
|---|---|---|---|
| `vibration` | ^2.0.0 | **^3.2.1** | **required** — 2.1.0 is `compileSdk 33`, below the floor |
| `google_mlkit_object_detection` | ^0.15.1 | **^0.17.1** | optional (35 → 36); taken while upgrading |
| `google_mlkit_commons` | ^0.11.0 | **^0.13.0** | optional (35 → 36); taken while upgrading |
| `camera` | ^0.11.0 | **^0.12.1** | optional; taken while upgrading |
| `permission_handler` | ^11.3.1 | **^11.3.1 (unchanged)** | **deliberately held back** — 13.x needs SDK 37, see Wall 2. 11.x gives `permission_handler_android 12.1.0` at `compileSdk 34`, which builds |

`permission_handler` is pinned below current **on purpose**, and the reason is
written into `pubspec.yaml` next to the pin so nobody "helpfully" bumps it.
Revisit when the project moves off AGP 9.1.0.

`flutter analyze` stayed clean across every bump, so none of the APIs the plan's
code uses have drifted. The one spot that could have bitten is
`FeedbackService._hasVibrator`, written as
`(await Vibration.hasVibrator()) == true` instead of the plan's `?? false` —
that works across the 1.x (`bool?`) and 2.x/3.x (`bool`) signatures alike.

**Worth reporting back to whoever wrote the plan:** §3's versions cost about 20
minutes of failed Gradle builds for anyone following the document on a current
toolchain.

## 8. Suggested next steps

1. Run `testing-guide.md` §3–§5 on the Android phone; retune the constants.
2. Install Xcode + CocoaPods, generate/finish `ios/`, repeat on the iPhone.
3. Extract `_pickMostThreatening` / `_toAlert` / `_shouldFire` into testable
   top-level functions and unit-test the heuristic — it's pure logic and
   currently has no automated coverage at all.
4. Build the Live Run screen (`runsense_flutter_plan.md` checkpoint 4), then flip
   `useMock` to exercise `LivePerceptionService` end to end.
5. Phase 2 (plan §11): swap the box-height heuristic for real depth. Only
   `_pickMostThreatening` changes — that isolation is the point of the design.

---

## 9. Post-review fixes (applied after the Phase 1 write-up above)

A review of this branch against `main` found four runtime defects. All four are
fixed; `flutter analyze` and `flutter test` pass after each.

### 9.1 Bounding boxes were scaled against the wrong coordinate space

**The bug.** ML Kit reports bounding boxes in the *upright* image — the frame
after `InputImageMetadata.rotation` is applied. `_onFrame` was dividing those
boxes by the *raw* camera dimensions (`image.width`/`image.height`). On a
portrait Android phone the sensor orientation is 90°, so the two spaces have
width and height swapped. For a 640×480 stream:

- `heightRatio = box.height / 480` where `box.height` ranges up to 640 →
  inflated past 1.0 and clamped, so nearly every detection crossed
  `_proximityHigh` (0.65) → permanent `AlertUrgency.high`: "DANGER", a 400 ms
  full-amplitude buzz, and the 700 ms repeat cadence, for everything in frame.
- `centerX = ... / 640` where the value ranges up to 480 → maximum 0.75, so the
  `> 0.66` "right" branch was almost unreachable and direction skewed left.

Neither symptom would look like a crash — the pipeline would appear to work and
simply be wrong, which is why it survived to review.

**The fix.** `InputImageConverter.fromCameraImage` now returns a
`ConvertedFrame` (`services/input_image_converter.dart`) carrying the
`InputImage` *and* the upright dimensions — the raw dimensions swapped when the
rotation is 90° or 270°. `_onFrame` passes `frame.width`/`frame.height` into
`_pickMostThreatening`. The heuristic itself is unchanged.

**Still needs a device.** The swap direction is correct per ML Kit's documented
behaviour and the official Flutter example's `coordinates_translator.dart`, but
it has not been observed on hardware. Confirm on the phone that an obstacle on
the runner's right is announced as "right".

### 9.2 STOP left the camera powered

`stop()` called `camera.stopStream()` only. The `CameraController` stayed
initialised, so `isInitialized` stayed true, `ObstacleDetectionScreen` kept
rendering a live `CameraPreview` under a status line reading "Detection
stopped.", and the sensor stayed on. Worse, `didChangeAppLifecycleState` routes
backgrounding through `stop()` — the exact situation the code's own comment says
crashes the plugin. `stop()` now calls `camera.dispose()`. `start()` re-creates
the controller, so the START/STOP cycle is unaffected.

### 9.3 A dropped TTS callback silenced the app permanently

`FeedbackService._speak` skips speech while `TtsService.isSpeaking`. That flag
was set on every `speak()` and cleared *only* by `setCompletionHandler`, which
flutter_tts does not fire reliably on every platform/engine (and `speak()` never
set `awaitSpeakCompletion(true)`). One missed callback would latch the flag true
and drop every subsequent alert for the rest of the run — silent failure, in the
one part of the app a blind runner depends on.

`TtsService` (`lib/services/tts_service.dart`) now tracks a `_speakingUntil`
deadline instead of a bare bool: `isSpeaking` self-clears after `_maxUtterance`
(5 s), and `setCancelHandler` / `setErrorHandler` clear it too. Worst case is
now one overlapping utterance, not permanent silence.

### 9.4 Leaving the module screen stopped app-wide speech

`FeedbackService.dispose()` called `_tts.stop()` on the shared, Provider-owned
`TtsService` — so popping the obstacle-detection screen cut off speech belonging
to whatever screen came next. The module borrows that service, it doesn't own
it; `dispose()` is now a documented no-op.

---

## 10. Merge with `main` (checkpoints 4–6 + GPS groundwork)

`origin/main` advanced by five commits (Live Run screen, Week Plan screen,
accessibility/nav pass, GPS + permission groundwork). Merged into this branch;
five files conflicted:

| File | Resolution |
| --- | --- |
| `lib/main.dart` | Kept `main`'s `Provider<LocationService>`; dropped its second `Provider<TtsService>` — this branch deliberately moved `TtsService` to the **top** of the provider list because `PerceptionService` reads it during creation and `MultiProvider` nests in list order. |
| `android/.../AndroidManifest.xml` | Union of both permission sets: CAMERA + VIBRATE + camera `uses-feature` (this branch) and ACCESS_FINE/COARSE_LOCATION (`main`). |
| `pubspec.yaml` | Both dependency blocks kept. `permission_handler ^11.3.1` appeared on both sides — now declared once, with the AGP 9.1.0 pinning rationale preserved. `main`'s comment saying camera/ML Kit were deliberately left out is gone; it described the pre-merge state. |
| `pubspec.lock` | Regenerated with `flutter pub get` from the merged manifest. |
| `PROGRESS.md` | `main`'s checkpoint 4/5/6 + GPS sections kept in order, Phase 2 section appended after them. This branch's stale "next up: build the Live Run screen" notes removed — `main` built it. |

`home_screen.dart` auto-merged cleanly: `main`'s Live Run / Week Plan navigation
and this branch's OBSTACLE DETECTION button coexist.

### 10.1 What the merge makes urgent

`LiveRunScreen` now exists, and it is exactly the consumer `LivePerceptionService`
(§5) was written for — it subscribes to `alertStream()` and calls
`startSimulation()`. Two problems that were latent before the merge are now on
the critical path to flipping `useMock` to `false`:

1. **Two camera owners.** `LiveRunScreen` (via `LivePerceptionService`) and
   `ObstacleDetectionScreen` each construct their own
   `ObstacleDetectionController`, and each controller owns a `CameraService`.
   Two `CameraController`s on one device means the second one throws. The
   `LivePerceptionService.controller` getter exists precisely so a host screen
   can share the single instance — the screen needs to use it.
2. **`LivePerceptionService` is never disposed.** `Provider<PerceptionService>`
   in `main.dart` has no `dispose:` callback, so the camera, the ML Kit detector
   and the alert subscription leak on teardown.

Neither is fixed here — both are integration decisions that belong with whoever
wires Live Run to the live pipeline.

---

## 11. Detection envelope retuned for running pace

Verified on the emulator with the host webcam as the back camera
(`hw.camera.back=webcam0`), which is what made the tuning testable at all — the
default `virtualscene` back camera only offers fixed furniture at a fixed
distance.

**The problem.** The original thresholds were set for walking distances. Box
height ratio stands in for distance: for an object of real height `H` at
distance `d`, with a ~60° vertical FOV the frame spans about `1.155 × d`, so
`d ≈ H / (1.155 × ratio)`. For a 1.7 m person the old constants worked out as:

| Constant | Old | Distance | Meaning |
| --- | --- | --- | --- |
| `_minHeightRatio` | 0.20 | ~7.4 m | below this, ignored entirely |
| `_proximityMedium` | 0.45 | ~3.3 m | Warning |
| `_proximityHigh` | 0.65 | ~2.3 m | DANGER |

DANGER at 2.3 m is **0.8 s** of warning at 3 m/s — less than reaction time, let
alone stopping distance. The alert would arrive after it was useful.

**The change.** Retuned for roughly 1.5 s of lead at running pace:

| Constant | New | Distance |
| --- | --- | --- |
| `_minHeightRatio` | 0.12 | ~12 m |
| `_proximityMedium` | 0.22 | ~7 m |
| `_proximityHigh` | 0.38 | ~4 m |

**The trade-off, stated plainly.** A lower floor lets more small, jittery
far-field boxes through, so expect more chatter from distant clutter. If that
becomes a problem, raise `_minHeightRatio` first — it gates everything else.

Two caveats on the distance figures: they assume a person-height object, so a
bollard, a curb or a low barrier will read as further away than it is; and the
FOV is assumed, not measured. They are a defensible starting point for field
testing, not calibrated values. Plan §13 step 10 still stands.

**A display hold was tried and removed.** An intermediate version held each
alert on screen for 2 s so a demo audience could read it, with escalation
exempt. Tested and reverted at the user's request: the readout is back to
responding immediately. If it's ever wanted for a demo, it was a single
`_alertHoldTime` constant plus a display-policy check in `_onFrame`.
