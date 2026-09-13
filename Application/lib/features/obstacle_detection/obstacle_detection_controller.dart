import 'dart:async';

import 'package:camera/camera.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:google_mlkit_object_detection/google_mlkit_object_detection.dart';

import '../../services/tts_service.dart';
import 'models/detected_obstacle.dart';
import 'models/obstacle_alert.dart';
import 'services/camera_service.dart';
import 'services/detection_service.dart';
import 'services/feedback_service.dart';
import 'services/input_image_converter.dart';

/// Orchestrates camera -> ML Kit -> alert -> feedback, and owns all the
/// *policy*: frame throttling, the proximity heuristic, and the "don't
/// re-alert on the same obstacle" rule. The decisions live here.
class ObstacleDetectionController extends ChangeNotifier {
  ObstacleDetectionController({
    required TtsService tts,
    this.speakAlerts = true,
  }) : feedback = FeedbackService(tts);

  final CameraService camera = CameraService();
  final DetectionService detector = DetectionService();
  final FeedbackService feedback;

  /// When false the controller still emits on [alerts] but stays silent — used
  /// when a host screen (Live Run) owns the speech instead of this module.
  final bool speakAlerts;

  final StreamController<ObstacleAlert> _alerts =
      StreamController<ObstacleAlert>.broadcast();

  /// Alerts that survived throttling. `LivePerceptionService` listens here.
  Stream<ObstacleAlert> get alerts => _alerts.stream;

  bool _running = false;
  bool _starting = false;
  bool _disposed = false;
  bool _isBusy = false; // true while a frame is being analyzed
  String? _error;
  ObstacleAlert? _lastAlert;

  DateTime _lastProcessed = DateTime.fromMillisecondsSinceEpoch(0);
  DateTime _lastHighAlert = DateTime.fromMillisecondsSinceEpoch(0);
  final Map<int, DateTime> _lastAlertPerObject = {}; // trackingId -> time

  // Tuning knobs — adjust during field testing (module plan §10, §13 step 10).
  static const _minFrameGap = Duration(milliseconds: 150); // ~6-7 fps analyzed
  static const _reAlertGap = Duration(seconds: 2);
  static const _highRepeatGap = Duration(milliseconds: 700);
  // Box-height ratio thresholds, set for RUNNING pace rather than walking.
  //
  // Ratio is a stand-in for distance: for an object of real height H at
  // distance d, with a ~60 degree vertical FOV, the frame spans about 1.155*d,
  // so d ~= H / (1.155 * ratio). Taking a 1.7m person, the values below put
  // first notice near 12m, Warning near 7m and DANGER near 4m — roughly 1.5s of
  // warning at 3 m/s, which is the point of alerting at all. The previous set
  // (0.20 / 0.45 / 0.65) only reached DANGER at ~2.3m, under a second out.
  //
  // The cost of the lower floor is more small, jittery far-field boxes getting
  // through; if far-off clutter starts chattering, raise _minHeightRatio first.
  static const _minHeightRatio = 0.12; // ~12m for a person; below this, ignore
  static const _proximityMedium = 0.22; // ~7m
  static const _proximityHigh = 0.38; // ~4m

  bool get isRunning => _running;
  bool get isStarting => _starting;
  String? get error => _error;
  ObstacleAlert? get lastAlert => _lastAlert;

  Future<void> start() async {
    if (_running || _starting) return;
    _starting = true;
    _error = null;
    notifyListeners();
    try {
      await camera.initialize();
      await feedback.initialize();
      await feedback.announce('Obstacle detection on');
      await camera.startStream(_onFrame);
      _running = true;
    } catch (e) {
      _error = 'Could not start the camera: $e';
      await feedback.announce('Could not start the camera');
      await camera.dispose();
    } finally {
      _starting = false;
      notifyListeners();
    }
  }

  Future<void> stop() async {
    if (!_running) return;
    _running = false;
    // Release the camera, don't just stop the stream: a still-initialised
    // controller keeps the sensor powered and the preview live, and the plugin
    // crashes if the app is backgrounded while holding one.
    await camera.dispose();
    await feedback.announce('Obstacle detection off');
    _lastAlertPerObject.clear();
    _lastAlert = null;
    notifyListeners();
  }

  void _onFrame(CameraImage image) async {
    if (!_running && !_starting) return;
    // THROTTLE 1: skip if we processed a frame very recently.
    final now = DateTime.now();
    if (now.difference(_lastProcessed) < _minFrameGap) return;
    // THROTTLE 2: skip if the previous frame is still being analyzed.
    if (_isBusy) return;
    _isBusy = true;
    _lastProcessed = now;

    try {
      final description = camera.description;
      if (description == null) return;

      final frame = InputImageConverter.fromCameraImage(
        image,
        description,
        DeviceOrientation.portraitUp, // MVP assumes the phone is held portrait
      );
      if (frame == null) return;

      final objects = await detector.detect(frame.image);
      // frame.width/height, not image.width/height: ML Kit measures boxes in
      // the rotated (upright) frame, so on a portrait phone the two are swapped.
      final obstacle =
          _pickMostThreatening(objects, frame.width, frame.height);
      if (obstacle == null) {
        // Path is clear again — drop the stale alert so the on-screen readout
        // stops claiming there's still something there.
        if (_lastAlert != null) {
          _lastAlert = null;
          if (!_disposed) notifyListeners();
        }
        return;
      }

      final alert = _toAlert(
        obstacle,
        DateTime.now().difference(now).inMilliseconds,
      );
      _pruneAlertHistory(now);
      if (!_shouldFire(alert, now)) return;

      _lastAlert = alert;
      if (!_alerts.isClosed) _alerts.add(alert);
      feedback.vibrateFor(alert);
      if (speakAlerts) feedback.speakFor(alert);
      if (!_disposed) notifyListeners();
    } catch (e) {
      debugPrint('Obstacle frame error: $e');
    } finally {
      _isBusy = false;
    }
  }

  /// HEURISTIC: the most threatening object is the one whose box is tallest
  /// (proxy for closest). Phase 2 swaps this for real depth — see §11.
  DetectedObstacle? _pickMostThreatening(
      List<DetectedObject> objects, int imgW, int imgH) {
    DetectedObstacle? best;
    for (final o in objects) {
      final box = o.boundingBox;
      final heightRatio = box.height / imgH; // proxy for closeness
      final centerX = (box.left + box.right) / 2 / imgW; // 0..1 across frame

      if (heightRatio < _minHeightRatio) continue;

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
        label: _bestLabel(o),
      );

      if (best == null || candidate.proximity > best.proximity) {
        best = candidate;
      }
    }
    return best;
  }

  String _bestLabel(DetectedObject o) {
    if (o.labels.isEmpty) return 'obstacle';
    final best = o.labels
        .reduce((a, b) => b.confidence > a.confidence ? b : a);
    return best.text.toLowerCase();
  }

  ObstacleAlert _toAlert(DetectedObstacle o, int latencyMs) {
    final AlertUrgency urgency;
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
      label: o.label,
      latencyMs: latencyMs,
    );
  }

  /// Don't re-alert the same tracked obstacle within [_reAlertGap].
  ///
  /// High urgency keeps warning for as long as the thing is that close, but on
  /// a [_highRepeatGap] cadence rather than every analyzed frame — firing a
  /// 400ms vibration ~7 times a second would just be a continuous blur.
  bool _shouldFire(ObstacleAlert alert, DateTime now) {
    if (alert.urgency == AlertUrgency.none) return false;
    final id = alert.trackingId;

    if (alert.urgency == AlertUrgency.high) {
      if (now.difference(_lastHighAlert) < _highRepeatGap) return false;
      _lastHighAlert = now;
      if (id != null) _lastAlertPerObject[id] = now;
      return true;
    }

    if (id == null) return true; // untracked -> just fire
    final last = _lastAlertPerObject[id];
    if (last != null && now.difference(last) < _reAlertGap) return false;
    _lastAlertPerObject[id] = now;
    return true;
  }

  /// Tracking ids are never reused but do keep climbing over a long run, so
  /// drop entries we can no longer be throttling against.
  void _pruneAlertHistory(DateTime now) {
    if (_lastAlertPerObject.length < 200) return;
    _lastAlertPerObject
        .removeWhere((_, t) => now.difference(t) > const Duration(seconds: 30));
  }

  @override
  void dispose() {
    _disposed = true;
    _running = false;
    _alerts.close();
    camera.dispose();
    detector.dispose();
    feedback.dispose();
    super.dispose();
  }
}
