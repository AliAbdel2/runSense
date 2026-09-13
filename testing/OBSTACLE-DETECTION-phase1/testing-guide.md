# Testing guide — Obstacle Detection module (Phase 1)

Covers `Application/lib/features/obstacle_detection/` and its wiring into the
app. Source of truth for behaviour: `Application/obstacle_detection_module_plan.md`.

## 0. Why there is no Postman collection here

This change adds **no HTTP surface**. It is an on-device camera → ML Kit →
speech/haptics pipeline that never leaves the phone; the FastAPI backend under
`app/` is untouched by it. A Postman collection would have nothing to call, so
one was deliberately not written rather than shipped empty. If/when the module
starts POSTing alerts to the backend (e.g. `app/routes/agent_routes.py` growing
an alert-ingest endpoint), add the collection at that point.

Everything below is **manual on-device testing** — the only kind that can
actually exercise a camera pipeline.

## 1. Before you can test

| Need | Why | Status on the dev Mac as of this change |
|---|---|---|
| Flutter SDK | build anything | installed at `~/development/flutter` |
| Android SDK | Android build | present at `~/Library/Android/sdk` |
| Full Xcode (not just Command Line Tools) | iOS build | **missing** — `xcode-select -p` points at `/Library/Developer/CommandLineTools` |
| CocoaPods | iOS pods | **missing** — `pod` not on PATH |
| `Application/ios/` | iOS platform folder | **generated as part of this change** (see §10) |

```bash
cd Application
flutter pub get
flutter analyze          # expect: no issues
flutter test             # expect: existing smoke test passes
```

## 2. Static / desk checks (no phone needed)

1. **Web build still works.** This is the regression the conditional import in
   `lib/features/obstacle_detection/obstacle_detection_entry.dart` exists to
   prevent — `dart:io` is a compile error on web.
   ```bash
   flutter build web --release
   ```
   Expected: succeeds. If it fails with "dart:io is not available", something
   now imports the module (or `google_mlkit_commons`) directly instead of going
   through `obstacle_detection_entry.dart`.
2. **Web app hides the feature.** `flutter run -d chrome` → the Home screen must
   show only START SESSION and ASK COACH. No OBSTACLE DETECTION button
   (`obstacleDetectionSupported` is `false` in the stub).
3. **Android debug build.**
   ```bash
   flutter build apk --debug
   ```
   Verified working (203 MB debug APK, ML Kit native libs present for arm64-v8a,
   armeabi-v7a and x86_64). If you change any of the five module dependencies in
   `pubspec.yaml`, re-run this — `flutter pub get` succeeding proves nothing
   about whether Gradle can build it. See `summary.md` §7 for the two version
   walls this project sits between.

## 3. Happy path — bench test (Android and iOS)

Do this indoors, sitting down, with a chair as the obstacle.

| # | Step | Expected |
|---|---|---|
| 3.1 | Launch app, tap OBSTACLE DETECTION on Home | Obstacle Detection screen opens; status line reads "Detection stopped." |
| 3.2 | Tap START | OS camera permission prompt on first run |
| 3.3 | Grant permission | Speech: "Obstacle detection on". Preview appears. Status line: "Detection running. Path clear." Button reads STOP |
| 3.4 | Hold a chair ~4 m away, centred | Status line shows `Notice: <label> ahead`. One short soft buzz. **No speech** (low urgency is haptic-only by design) |
| 3.5 | Walk the chair to ~2 m | Escalates to `Warning: … ahead`. Double buzz + spoken "ahead" |
| 3.6 | Walk the chair to ~1 m (fills most of the frame) | Escalates to `DANGER: … ahead`. Long strong buzz + spoken "ahead, stop", repeating roughly once a second while it stays that close |
| 3.7 | Tap STOP | Speech: "Obstacle detection off". Status line: "Detection stopped." Preview freezes/clears |

The escalation thresholds are box-height-as-fraction-of-frame, not metres:
`< 0.20` ignored, `0.20–0.45` low, `0.45–0.65` medium, `≥ 0.65` high
(`obstacle_detection_controller.dart`, the `_proximity*` / `_minHeightRatio`
constants). Distances above are what those work out to for a chair-sized object
on a medium-resolution rear camera — expect to retune per device (plan §13
step 10).

## 4. Direction test

Hold the obstacle in the left third / middle / right third of the frame.

| Obstacle position | Spoken word | Status line |
|---|---|---|
| Left third (centre-x < 0.33) | "left" | `… left` |
| Middle | "ahead" | `… ahead` |
| Right third (centre-x > 0.66) | "right" | `… right` |

Note the frame is split on the **bounding-box centre**, so an obstacle
straddling a boundary snaps to whichever side its centre falls in.

## 5. Throttling test (DoD #4) — the one most likely to regress

1. Hold a static obstacle at medium range and **do not move it** for 10 s.
   - Expected: **one** spoken "ahead"/"left"/"right", then silence, then at most
     one more every ~2 s (`_reAlertGap`) — not a stream of them.
   - If it repeats every frame: ML Kit tracking is returning `trackingId: null`
     (untracked objects deliberately always fire — see `_shouldFire`). Confirm
     `DetectionMode.stream` is still set in `detection_service.dart`.
2. Hold it at close range for 10 s.
   - Expected: repeats at roughly **1.4×/second** (`_highRepeatGap` = 700 ms),
     not ~7×/second.
   - *This differs from the plan's §8 code*, which returns `true` unconditionally
     for high urgency and would fire on every analysed frame — a 400 ms
     vibration restarted every 150 ms is a continuous blur and the speech guard
     swallows most of the words. Deliberate deviation; see `summary.md`.
3. Watch the preview while doing (1) — it must stay smooth. Jank means a
   throttle was removed or `_isBusy` isn't reset in the `finally`.

## 6. Failure cases

| # | Case | How | Expected |
|---|---|---|---|
| 6.1 | Permission denied | Deny the camera prompt (or revoke in Settings, relaunch, tap START) | Speech: "Camera permission is needed to detect obstacles". No crash. Button stays on START |
| 6.2 | Permission permanently denied | Deny twice on Android | Same as 6.1 (`permission_handler` returns `permanentlyDenied`, which is not `isGranted`) |
| 6.3 | Camera fails to open | Hard to force; open another camera app in split-screen and tap START | Speech: "Could not start the camera"; the error text renders where the preview would be; no crash |
| 6.4 | Backgrounding mid-run | Start detection, then swipe to home | Streaming stops (lifecycle observer in `obstacle_detection_screen.dart`). Returning to the app shows the stopped state — restart manually. **Must not crash** — streaming while backgrounded is a known camera-plugin crash |
| 6.5 | No vibration motor | Test on a device/emulator without one | Speech still works; no crash (`FeedbackService._hasVibrator` guard) |
| 6.6 | Web | `flutter run -d chrome`, navigate to `/obstacle-detection` directly | The stub "needs the phone camera" screen, not a crash |

## 7. Accessibility pass (DoD #6)

Do this with the screen **off-axis or covered** — no peeking.

1. Enable TalkBack (Android) / VoiceOver (iOS).
2. From Home, swipe to the third button. It must announce
   **"Open obstacle detection, button"**.
3. Double-tap to activate. The Obstacle Detection screen opens.
4. Swipe to the main button. It must announce **"Start obstacle detection,
   button"** — and after activation, **"Stop obstacle detection, button"**.
5. The status line is a `liveRegion`, so the screen reader should re-announce it
   as it changes. Verify this doesn't fight with the alert speech; if they talk
   over each other, that's a finding worth raising (the app TTS and the screen
   reader are separate audio channels and neither knows about the other).
6. Both buttons come from `BigActionButton` (≥72 px tall, full width).

## 8. Cross-platform (plan §12.4)

Run §3–§5 on **both** phones. The specific thing to watch for is a preview that
looks sideways, stretched, or scrambled on one platform and fine on the other —
that means the rotation/format handling in `input_image_converter.dart` is wrong
for that device, and detection will be silently returning nothing.

Quick diagnosis if nothing is ever detected:
- Add a `debugPrint` of `objects.length` in `_onFrame` — 0 every frame with a
  large object in view means a bad `InputImage`, not a bad heuristic.
- Confirm `imageFormatGroup` is `nv21` on Android and `bgra8888` on iOS
  (`camera_service.dart`).
- The converter returns `null` (frame skipped) on any mismatch, so a broken
  format looks identical to "no obstacles" — which is why the print matters.

## 9. Field test — safety

Per plan §12.7: phone held chest-height, empty path, **a sighted spotter walking
alongside at all times**. Never test this on a runner without a spotter. The
Phase 1 proximity heuristic is a box-size proxy, not a distance measurement —
it has no idea how big the object actually is, so a distant lorry and a nearby
bollard can produce the same alert.

## 10. Not covered / known gaps

### iOS — generated, never built

`Application/ios/` did not exist before this change; it was generated fresh
(bundle id `com.runsense.runsense`, matching Android) and
`NSCameraUsageDescription` was added to `ios/Runner/Info.plist` per plan §4.3.
`plutil -lint` confirms the plist is valid. Nothing beyond that is verified —
Xcode and CocoaPods are not installed, so **nothing iOS has been compiled**.

Two things whoever picks this up on a Mac with Xcode should know:

1. **Plan §4.4 is already satisfied, differently than the plan describes.** There
   is no `ios/Podfile` yet — Flutter generates it on the first
   `flutter build ios` / `pod install`, so there is no `platform :ios` line to
   uncomment. What actually governs the floor is
   `IPHONEOS_DEPLOYMENT_TARGET`, and Flutter 3.47's template already sets it to
   **15.0** in `ios/Runner.xcodeproj/project.pbxproj`, which is what §4.4 asks
   for. If ML Kit demands higher on first `pod install`, raise it there.
2. **`permission_handler` needs a Podfile macro on iOS.** Without a
   `GCC_PREPROCESSOR_DEFINITIONS` block in `post_install` declaring
   `PERMISSION_CAMERA=1`, it compiles in *every* permission handler, which draws
   App Store review complaints about permissions the app never declares. Add it
   once the Podfile exists — see the permission_handler README.
- **Stereo beeps** (plan §7 "future feedback upgrade") not implemented.
- **`LivePerceptionService` is wired but not exercised** — `useMock` is still
  `true` in `lib/app_config.dart`, and the Live Run screen it would feed is
  checkpoint 4 of `runsense_flutter_plan.md`, which doesn't exist yet. To try it
  early: set `useMock = false` — but note that also makes Plan/Session/AgentChat
  throw `UnimplementedError`, so the app won't get past Home.
- **No automated tests** for the pipeline. The heuristic (`_pickMostThreatening`,
  `_toAlert`, `_shouldFire`) is pure and unit-testable, but it's private to the
  controller; extracting it to a testable top-level function is a worthwhile
  follow-up.
