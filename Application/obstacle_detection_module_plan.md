# Obstacle Detection Module — Implementation Plan

**Project:** Fitness/running coach app for blind & low-vision runners (Flutter)
**Module owner:** (you)
**Scope of this doc:** ONLY the real-time obstacle-detection-while-running feature. Not Strava, not Google Calendar, not the coaching/workout logic — teammates own those.
**Audience:** An entry-level engineer who has the app's existing Flutter codebase open. This document tells you exactly what to build, in what order, and gives you the code.

**Status:** Phase 2 — built after `runsense_flutter_plan.md`'s mocked app skeleton (Checkpoints 1-7) ships. See that plan's section 10 for how this module plugs in as `LivePerceptionService`.

---

## 0. TL;DR of the approach (read this first)

We detect obstacles using the phone camera only (no wearables — we don't have them). The pipeline is:

```
Camera frames  ->  convert to ML Kit format  ->  ML Kit object detector
     ->  analyze detections (which objects, where, how close)
     ->  turn that into feedback (speech + beeps + vibration)
```

We build this in **two phases**:

- **Phase 1 (this doc, the MVP):** ML Kit object detection + a *proximity heuristic* (a bigger box near the bottom-center of the frame = a closer obstacle in the runner's path). Pure Dart, runs on both iOS and Android identically. This is everything below unless marked "Phase 2".
- **Phase 2 (scoped, not built yet):** Replace the heuristic with real depth (ARCore Depth API on Android, ARKit scene depth on iOS) via native platform channels. This is a native task for a more senior engineer. See §11.

**Why not real depth now?** There is no maintained Flutter/Dart plugin that gives us a continuous depth map for this use case. The AR plugins on pub.dev are for placing 3D models and measuring between tapped points, not streaming depth. Real depth = native code on both platforms. We are not blocking the MVP on that.

**Why ML Kit and not a custom YOLO model?** For "is there a large thing in my path and roughly where," ML Kit's built-in object detector in stream mode (with tracking) is enough, needs zero model training, is free, on-device, offline, and cross-platform. Custom models are a Phase 2+ optimization.

---

## 1. Definition of Done (acceptance criteria)

The module is done for the MVP when ALL of these are true. Test them on both the iPhone and the Android phone.

1. There is a screen (`ObstacleDetectionScreen`) that, when opened, starts the camera and begins processing frames.
2. When a large object enters the center-bottom of the camera view and grows (i.e. the runner approaches it), the app gives an escalating audio + haptic alert.
3. The alert conveys **direction** (left / center / right) via spoken word and/or stereo, and **urgency** (how close) via beep frequency + vibration intensity.
4. Alerts are **throttled**: the app does not spam the same alert every frame. Max one spoken alert per obstacle per ~2 seconds.
5. The app processes frames without freezing the UI (target: analyze ~5–8 frames/sec, drop the rest).
6. The screen is fully usable by a blind user: large touch targets, a screen-reader label on every control, and a spoken confirmation when detection starts and stops.
7. Camera permission is requested gracefully; if denied, the app speaks an explanation instead of crashing.
8. Starting/stopping detection is controlled by a single obvious button (and ideally a voice or double-tap gesture).

---

## 2. Prerequisites & assumptions about the existing codebase

Confirm these before you start. If any are false, flag it to the team lead.

- The app is a Flutter app using a state-management approach already chosen by the team. This doc uses **plain `ChangeNotifier` + `Provider`** for the module's state because it's the lowest-friction. If the team uses Riverpod/Bloc, wrap the same services accordingly — the service classes below are framework-agnostic on purpose.
- Minimum SDKs: **Android `minSdkVersion` 21+**, **iOS deployment target 15.0+**. Bump them in the config step if lower.
- Dart SDK is **3.8+** (required by the current ML Kit plugin).
- There is a navigation setup (e.g. a router or `Navigator`) you can push a new screen onto. You will add one route: `ObstacleDetectionScreen`.

> You do NOT need to understand the coaching or Strava code. This module is self-contained under `lib/features/obstacle_detection/`.

---

## 3. Dependencies

Add these to `pubspec.yaml` under `dependencies:` (versions are known-good as of writing — run `flutter pub get` and use the resolved latest compatible if newer):

```yaml
dependencies:
  camera: ^0.11.0                       # camera preview + frame stream
  google_mlkit_object_detection: ^0.15.1 # ML Kit object detection + tracking
  google_mlkit_commons: ^0.11.0         # InputImage types (pulled in transitively, pin anyway)
  flutter_tts: ^4.0.2                   # spoken feedback
  vibration: ^2.0.0                     # haptic feedback with amplitude control
  permission_handler: ^11.3.1           # runtime camera permission
  provider: ^6.1.2                      # state (skip if team uses another)
```

Then:

```bash
flutter pub get
```

---

## 4. Platform configuration (do this once, carefully — most bugs live here)

### 4.1 Android — `android/app/src/main/AndroidManifest.xml`

Inside `<manifest>`, above `<application>`:

```xml
<uses-permission android:name="android.permission.CAMERA" />
<uses-permission android:name="android.permission.VIBRATE" />
<uses-feature android:name="android.hardware.camera" android:required="true" />
```

### 4.2 Android — `android/app/build.gradle`

Ensure:

```gradle
android {
    defaultConfig {
        minSdkVersion 21   // or higher; must be >= 21
    }
}
```

### 4.3 iOS — `ios/Runner/Info.plist`

Inside the top-level `<dict>`:

```xml
<key>NSCameraUsageDescription</key>
<string>The camera is used to detect obstacles ahead of you while you run.</string>
```

(TTS and vibration need no extra iOS keys.)

### 4.4 iOS deployment target

In `ios/Podfile`, ensure the platform line is uncommented and set:

```ruby
platform :ios, '15.0'
```

Then:

```bash
cd ios && pod install && cd ..
```

> If `pod install` complains about ML Kit min iOS version, raise `15.0` to whatever it demands. That's the single most common iOS build failure here.

---

## 5. Folder & file structure to create

Create exactly this under `lib/`:

```
lib/features/obstacle_detection/
├── obstacle_detection_screen.dart      # the UI screen (§9)
├── obstacle_detection_controller.dart  # orchestrates everything (§8)
├── services/
│   ├── camera_service.dart             # owns the camera + frame stream (§6.1)
│   ├── input_image_converter.dart      # CameraImage -> ML Kit InputImage (§6.2)
│   ├── detection_service.dart          # wraps ML Kit ObjectDetector (§6.3)
│   └── feedback_service.dart           # speech + beep + vibration (§7)
└── models/
    ├── detected_obstacle.dart          # a single obstacle + its analysis (§6.4)
    └── obstacle_alert.dart             # what to tell the user (§6.4)
```

Build the files in the order of the sections below. Each section is a self-contained ticket.

---

## 6. The detection pipeline

### 6.1 `camera_service.dart` — own the camera and stream frames

Responsibilities: pick the back camera, start the preview, and expose a stream of raw frames. **Critical:** set the image format group so ML Kit can read the bytes (`nv21` on Android, `bgra8888` on iOS).

```dart
import 'dart:io';
import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart';

/// Owns the physical camera and emits raw frames for processing.
class CameraService {
  CameraController? _controller;
  CameraDescription? _camera;

  CameraController? get controller => _controller;
  CameraDescription? get description => _camera;
  bool get isInitialized => _controller?.value.isInitialized ?? false;

  /// Call once before use. Picks the rear camera and starts it.
  Future<void> initialize() async {
    final cameras = await availableCameras();
    _camera = cameras.firstWhere(
      (c) => c.lensDirection == CameraLensDirection.back,
      orElse: () => cameras.first,
    );

    _controller = CameraController(
      _camera!,
      ResolutionPreset.medium, // medium is plenty; higher = slower, no benefit
      enableAudio: false,
      imageFormatGroup:
          Platform.isAndroid ? ImageFormatGroup.nv21 : ImageFormatGroup.bgra8888,
    );

    await _controller!.initialize();
  }

  /// Start delivering frames. The callback fires on EVERY frame — throttle downstream.
  Future<void> startStream(void Function(CameraImage image) onFrame) async {
    if (!isInitialized) return;
    await _controller!.startImageStream(onFrame);
  }

  Future<void> stopStream() async {
    if (_controller?.value.isStreamingImages ?? false) {
      await _controller!.stopImageStream();
    }
  }

  Future<void> dispose() async {
    await stopStream();
    await _controller?.dispose();
    _controller = null;
  }
}
```

### 6.2 `input_image_converter.dart` — the format bridge (the tricky bit)

ML Kit wants an `InputImage` with exact metadata. Getting `bytesPerRow` or rotation wrong makes the image look scrambled and detection silently fails. This is battle-tested boilerplate — copy it as-is.

```dart
import 'dart:io';
import 'package:camera/camera.dart';
import 'package:flutter/services.dart';
import 'package:google_mlkit_commons/google_mlkit_commons.dart';

class InputImageConverter {
  // Maps device orientation to degrees for Android rotation compensation.
  static const _orientations = {
    DeviceOrientation.portraitUp: 0,
    DeviceOrientation.landscapeLeft: 90,
    DeviceOrientation.portraitDown: 180,
    DeviceOrientation.landscapeRight: 270,
  };

  /// Returns null if the frame can't be converted — caller must skip it.
  static InputImage? fromCameraImage(
    CameraImage image,
    CameraDescription camera,
    DeviceOrientation deviceOrientation,
  ) {
    final sensorOrientation = camera.sensorOrientation;

    InputImageRotation? rotation;
    if (Platform.isIOS) {
      rotation = InputImageRotationValue.fromRawValue(sensorOrientation);
    } else {
      var compensation = _orientations[deviceOrientation];
      if (compensation == null) return null;
      if (camera.lensDirection == CameraLensDirection.front) {
        compensation = (sensorOrientation + compensation) % 360;
      } else {
        compensation = (sensorOrientation - compensation + 360) % 360;
      }
      rotation = InputImageRotationValue.fromRawValue(compensation);
    }
    if (rotation == null) return null;

    final format = InputImageFormatValue.fromRawValue(image.format.raw);
    if (format == null ||
        (Platform.isAndroid && format != InputImageFormat.nv21) ||
        (Platform.isIOS && format != InputImageFormat.bgra8888)) {
      return null;
    }

    // With nv21 / bgra8888 the camera gives a single plane.
    if (image.planes.length != 1) return null;
    final plane = image.planes.first;

    return InputImage.fromBytes(
      bytes: plane.bytes,
      metadata: InputImageMetadata(
        size: Size(image.width.toDouble(), image.height.toDouble()),
        rotation: rotation,
        format: format,
        bytesPerRow: plane.bytesPerRow,
      ),
    );
  }
}
```

### 6.3 `detection_service.dart` — wrap ML Kit

Stream mode + multiple objects + tracking. Tracking gives each object a stable `trackingId`, which we use to avoid re-alerting on the same obstacle every frame.

```dart
import 'package:google_mlkit_object_detection/google_mlkit_object_detection.dart';
import 'package:google_mlkit_commons/google_mlkit_commons.dart';

class DetectionService {
  late final ObjectDetector _detector;

  DetectionService() {
    final options = ObjectDetectorOptions(
      mode: DetectionMode.stream,      // continuous video
      classifyObjects: true,           // gives a coarse label when it can
      multipleObjects: true,           // detect several obstacles at once
    );
    _detector = ObjectDetector(options: options);
  }

  Future<List<DetectedObject>> detect(InputImage image) {
    return _detector.processImage(image);
  }

  Future<void> dispose() => _detector.close();
}
```

### 6.4 `models/` — the data we pass around

`detected_obstacle.dart`:

```dart
import 'dart:ui';

/// Where in the frame an obstacle sits, and how "close" our heuristic thinks it is.
enum ObstacleDirection { left, center, right }

class DetectedObstacle {
  final int? trackingId;              // stable id across frames (may be null)
  final Rect boundingBox;             // in image coordinates
  final ObstacleDirection direction;
  final double proximity;             // 0.0 (far) .. 1.0 (very close) — heuristic

  const DetectedObstacle({
    required this.trackingId,
    required this.boundingBox,
    required this.direction,
    required this.proximity,
  });
}
```

`obstacle_alert.dart`:

```dart
import 'detected_obstacle.dart';

enum AlertUrgency { none, low, medium, high }

class ObstacleAlert {
  final ObstacleDirection direction;
  final AlertUrgency urgency;
  final int? trackingId;

  const ObstacleAlert({
    required this.direction,
    required this.urgency,
    required this.trackingId,
  });
}
```

---

## 7. `feedback_service.dart` — how the runner actually gets told

This is the accessibility heart of the module. It converts an `ObstacleAlert` into speech + beeps + vibration. Keep messages SHORT — a runner has no time for sentences.

Feedback design rules:
- **Direction** → the spoken word: "left", "ahead", "right".
- **Urgency** → escalation: low = nothing spoken, just a soft single vibration; medium = a spoken direction + double vibration; high = spoken direction + long strong vibration.
- Never talk over yourself. If speech is already playing, skip the new spoken line but still vibrate.

```dart
import 'package:flutter_tts/flutter_tts.dart';
import 'package:vibration/vibration.dart';
import '../models/obstacle_alert.dart';
import '../models/detected_obstacle.dart';

class FeedbackService {
  final FlutterTts _tts = FlutterTts();
  bool _speaking = false;
  bool _hasVibrator = false;

  Future<void> initialize() async {
    await _tts.setSpeechRate(0.6); // clear but quick
    await _tts.setVolume(1.0);
    _tts.setCompletionHandler(() => _speaking = false);
    _hasVibrator = await Vibration.hasVibrator() ?? false;
  }

  Future<void> announce(String message) async {
    // Used for start/stop confirmations, not per-frame alerts.
    await _tts.stop();
    _speaking = true;
    await _tts.speak(message);
  }

  Future<void> deliver(ObstacleAlert alert) async {
    switch (alert.urgency) {
      case AlertUrgency.none:
        return;
      case AlertUrgency.low:
        _vibrate(duration: 80, amplitude: 60);
        break;
      case AlertUrgency.medium:
        _vibrate(pattern: [0, 100, 80, 100], amplitude: 150);
        _speak(_word(alert.direction));
        break;
      case AlertUrgency.high:
        _vibrate(duration: 400, amplitude: 255);
        _speak('${_word(alert.direction)}, stop');
        break;
    }
  }

  void _speak(String text) {
    if (_speaking) return; // don't stack speech
    _speaking = true;
    _tts.speak(text);
  }

  String _word(ObstacleDirection d) {
    switch (d) {
      case ObstacleDirection.left:
        return 'left';
      case ObstacleDirection.right:
        return 'right';
      case ObstacleDirection.center:
        return 'ahead';
    }
  }

  void _vibrate({int? duration, List<int>? pattern, int amplitude = 128}) {
    if (!_hasVibrator) return;
    if (pattern != null) {
      Vibration.vibrate(pattern: pattern);
    } else {
      Vibration.vibrate(duration: duration ?? 100, amplitude: amplitude);
    }
  }

  Future<void> dispose() async {
    await _tts.stop();
  }
}
```

> **Future feedback upgrade (optional, easy win):** play a stereo beep panned left/right so direction is felt without words. Add the `just_audio` package and pan a short tone. Nice-to-have, not required for DoD.

---

## 8. `obstacle_detection_controller.dart` — the orchestrator

This ties it together and holds all the *policy*: throttling, the proximity heuristic, and the "don't re-alert the same obstacle" logic. This is the file where the actual decisions live — read it slowly.

```dart
import 'dart:io';
import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:google_mlkit_object_detection/google_mlkit_object_detection.dart';

import 'services/camera_service.dart';
import 'services/detection_service.dart';
import 'services/feedback_service.dart';
import 'services/input_image_converter.dart';
import 'models/detected_obstacle.dart';
import 'models/obstacle_alert.dart';

class ObstacleDetectionController extends ChangeNotifier {
  final CameraService camera = CameraService();
  final DetectionService detector = DetectionService();
  final FeedbackService feedback = FeedbackService();

  bool _running = false;
  bool _isBusy = false;               // true while a frame is being analyzed
  DateTime _lastProcessed = DateTime.fromMillisecondsSinceEpoch(0);
  final Map<int, DateTime> _lastAlertPerObject = {}; // trackingId -> time

  // Tuning knobs — adjust during field testing.
  static const _minFrameGap = Duration(milliseconds: 150); // ~6-7 fps analyzed
  static const _reAlertGap = Duration(seconds: 2);
  static const _proximityMedium = 0.45; // box-height ratio thresholds
  static const _proximityHigh = 0.65;

  bool get isRunning => _running;

  Future<void> start() async {
    await camera.initialize();
    await feedback.initialize();
    await feedback.announce('Obstacle detection on');
    await camera.startStream(_onFrame);
    _running = true;
    notifyListeners();
  }

  Future<void> stop() async {
    _running = false;
    await camera.stopStream();
    await feedback.announce('Obstacle detection off');
    notifyListeners();
  }

  void _onFrame(CameraImage image) async {
    // THROTTLE 1: skip if we processed a frame very recently.
    final now = DateTime.now();
    if (now.difference(_lastProcessed) < _minFrameGap) return;
    // THROTTLE 2: skip if the previous frame is still being analyzed.
    if (_isBusy) return;
    _isBusy = true;
    _lastProcessed = now;

    try {
      final inputImage = InputImageConverter.fromCameraImage(
        image,
        camera.description!,
        DeviceOrientation.portraitUp, // assume portrait for MVP
      );
      if (inputImage == null) return;

      final objects = await detector.detect(inputImage);
      final obstacle = _pickMostThreatening(objects, image.width, image.height);
      if (obstacle == null) return;

      final alert = _toAlert(obstacle);
      if (_shouldFire(alert, now)) {
        await feedback.deliver(alert);
      }
    } catch (e) {
      debugPrint('Obstacle frame error: $e');
    } finally {
      _isBusy = false;
    }
  }

  /// HEURISTIC: the most threatening object is the one whose box is tallest
  /// (closest) AND near the center-bottom (in the runner's path).
  DetectedObstacle? _pickMostThreatening(
      List<DetectedObject> objects, int imgW, int imgH) {
    DetectedObstacle? best;
    for (final o in objects) {
      final box = o.boundingBox;
      final heightRatio = box.height / imgH;              // proxy for closeness
      final centerX = (box.left + box.right) / 2 / imgW;  // 0..1 across frame

      // Ignore tiny/far specks.
      if (heightRatio < 0.20) continue;

      final direction = centerX < 0.33
          ? ObstacleDirection.left
          : centerX > 0.66
              ? ObstacleDirection.right
              : ObstacleDirection.center;

      final candidate = DetectedObstacle(
        trackingId: o.trackingId,
        boundingBox: box,
        direction: direction,
        proximity: heightRatio.clamp(0.0, 1.0),
      );

      if (best == null || candidate.proximity > best.proximity) {
        best = candidate;
      }
    }
    return best;
  }

  ObstacleAlert _toAlert(DetectedObstacle o) {
    AlertUrgency urgency;
    if (o.proximity >= _proximityHigh) {
      urgency = AlertUrgency.high;
    } else if (o.proximity >= _proximityMedium) {
      urgency = AlertUrgency.medium;
    } else {
      urgency = AlertUrgency.low;
    }
    return ObstacleAlert(
      direction: o.direction,
      urgency: urgency,
      trackingId: o.trackingId,
    );
  }

  /// Don't re-alert the same tracked obstacle within _reAlertGap,
  /// UNLESS urgency escalated to high (then always warn).
  bool _shouldFire(ObstacleAlert alert, DateTime now) {
    if (alert.urgency == AlertUrgency.none) return false;
    if (alert.urgency == AlertUrgency.high) return true;
    final id = alert.trackingId;
    if (id == null) return true; // untracked -> just fire
    final last = _lastAlertPerObject[id];
    if (last != null && now.difference(last) < _reAlertGap) return false;
    _lastAlertPerObject[id] = now;
    return true;
  }

  @override
  void dispose() {
    camera.dispose();
    detector.dispose();
    feedback.dispose();
    super.dispose();
  }
}
```

---

## 9. `obstacle_detection_screen.dart` — the UI

The UI is intentionally minimal because the primary user cannot see it. It shows the camera preview (useful for a sighted tester/spotter) and one big accessible Start/Stop control. Every interactive element has a `Semantics` label so TalkBack/VoiceOver reads it.

```dart
import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:permission_handler/permission_handler.dart';
import 'obstacle_detection_controller.dart';

class ObstacleDetectionScreen extends StatelessWidget {
  const ObstacleDetectionScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => ObstacleDetectionController(),
      child: const _ObstacleDetectionView(),
    );
  }
}

class _ObstacleDetectionView extends StatefulWidget {
  const _ObstacleDetectionView();
  @override
  State<_ObstacleDetectionView> createState() => _ObstacleDetectionViewState();
}

class _ObstacleDetectionViewState extends State<_ObstacleDetectionView> {
  Future<bool> _ensurePermission() async {
    final status = await Permission.camera.request();
    return status.isGranted;
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<ObstacleDetectionController>();

    return Scaffold(
      appBar: AppBar(title: const Text('Obstacle Detection')),
      body: Column(
        children: [
          Expanded(
            child: controller.camera.isInitialized
                ? CameraPreview(controller.camera.controller!)
                : const Center(child: Text('Camera off')),
          ),
          Padding(
            padding: const EdgeInsets.all(24),
            child: Semantics(
              button: true,
              label: controller.isRunning
                  ? 'Stop obstacle detection'
                  : 'Start obstacle detection',
              child: SizedBox(
                width: double.infinity,
                height: 88, // large touch target
                child: ElevatedButton(
                  onPressed: () async {
                    if (controller.isRunning) {
                      await controller.stop();
                    } else {
                      if (await _ensurePermission()) {
                        await controller.start();
                      } else {
                        await controller.feedback.announce(
                          'Camera permission is needed to detect obstacles',
                        );
                      }
                    }
                  },
                  child: Text(
                    controller.isRunning ? 'STOP' : 'START',
                    style: const TextStyle(fontSize: 28),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
```

Wire the route into wherever the team registers routes, e.g.:

```dart
// in your router / route table
'/obstacle-detection': (context) => const ObstacleDetectionScreen(),
```

---

## 10. Performance & threading notes (why the throttling exists)

- ML Kit runs its inference off the Dart isolate natively, but the **conversion + orchestration** runs on the UI isolate. That's fine as long as we don't try to process every frame. The two throttles in `_onFrame` (min gap + `_isBusy` guard) are what keep the UI smooth. **Do not remove them.**
- Target ~5–8 analyzed frames/sec. A running person doesn't need 30fps of obstacle checks; they need timely ones. If the phone struggles, raise `_minFrameGap` to 200ms.
- Keep `ResolutionPreset.medium`. Higher resolution = slower inference with no accuracy gain for large-obstacle detection.
- If you later see UI jank on the older phone, move the `InputImageConverter` call into an isolate via `compute()`. Not needed for MVP.

---

## 11. Phase 2 — real depth (scoped, NOT in this ticket)

When a senior engineer is available, replace the proximity *heuristic* (§8 `_pickMostThreatening`) with true depth:

- **Android:** ARCore **Depth API** gives a per-pixel depth image. Access it in native Kotlin, sample the depth at the center of each ML Kit bounding box, send meters back to Dart over a `MethodChannel`/`EventChannel`.
- **iOS:** ARKit **scene depth** (`ARFrame.sceneDepth`, LiDAR-accurate on Pro devices, estimated on others) via native Swift, same channel bridge.
- Keep the exact same `DetectedObstacle` / `ObstacleAlert` models — only the source of `proximity` changes (from box-height ratio to real meters). Everything downstream (feedback, throttling) is unchanged.

This is deliberately isolated so Phase 1 ships and Phase 2 is a drop-in swap of one method.

---

## 12. Testing plan (with only 2 phones, no wearables)

1. **Bench test:** open the screen, tap Start, walk a chair toward the camera slowly. Confirm the alert escalates low → medium → high as the chair fills more of the frame.
2. **Direction test:** move the obstacle to the left third, center, right third. Confirm spoken word matches.
3. **Throttle test:** hold a static obstacle in view; confirm you get ONE medium alert, not a stream of them, until it gets closer (escalates to high).
4. **Both platforms:** run 1–3 on the iPhone and the Android phone. Watch specifically for a scrambled/rotated preview on one platform — that means the `InputImageConverter` rotation/format is off for that device; recheck §6.2 and §4.
5. **Permission denial:** deny camera permission once and confirm the app speaks the explanation instead of crashing.
6. **Accessibility pass:** turn on VoiceOver (iOS) / TalkBack (Android), navigate to and operate the Start button using only the screen reader.
7. **Field test (safely):** have a sighted spotter walk beside the tester holding the phone chest-height, on an empty path. This is your stand-in for the eventual harness. Never test on an actual runner without a spotter.

---

## 13. Ordered task checklist (turn each into a ticket)

1. [ ] Add dependencies (§3), run `pub get`, confirm the app still builds on both platforms.
2. [ ] Do all platform config (§4). Build a bare app that just requests camera permission and shows a preview. **Ship nothing else until the preview works on both phones.**
3. [ ] Create `models/` (§6.4).
4. [ ] Implement `CameraService` (§6.1) and confirm frames arrive (log a counter in the stream callback).
5. [ ] Implement `InputImageConverter` (§6.2).
6. [ ] Implement `DetectionService` (§6.3); log detected object count per frame.
7. [ ] Implement `FeedbackService` (§7); test speech + vibration in isolation with a debug button.
8. [ ] Implement `ObstacleDetectionController` (§8) wiring it all together.
9. [ ] Build `ObstacleDetectionScreen` (§9) and register the route.
10. [ ] Run the full testing plan (§12); tune the four constants in §8.
11. [ ] Demo against the Definition of Done (§1).

---

## 14. Gotchas / FAQ

- **Preview is sideways or garbled on one platform.** Rotation/format mismatch — the #1 issue. Recheck §6.2 and the `imageFormatGroup` in §6.1. Android must be `nv21`, iOS must be `bgra8888`.
- **`detect()` returns nothing ever.** Almost always a bad `InputImage` (wrong `bytesPerRow`/rotation) so the model sees garbage. Add a debug view that draws the bounding boxes over the preview to confirm the model is seeing a sane image.
- **UI freezes.** A throttle got removed or `_isBusy` isn't being reset in the `finally`. Check §8.
- **iOS build fails on `pod install`.** Raise the iOS deployment target (§4.4) to whatever ML Kit demands.
- **"Which object is the obstacle?"** For MVP we don't care about the label — we care about a big box in the center-bottom that's growing. That's what the heuristic keys on. Classification labels are a nice-to-have for later ("person ahead" vs "car ahead").
