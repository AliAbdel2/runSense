import 'package:vibration/vibration.dart';

import '../../../services/tts_service.dart';
import '../models/detected_obstacle.dart';
import '../models/obstacle_alert.dart';

/// Turns an [ObstacleAlert] into something a runner can hear and feel.
///
/// Design rules (module plan §7):
///  - direction  -> the spoken word: "left", "ahead", "right"
///  - urgency    -> escalation: low = a soft buzz only, medium = spoken
///    direction + double buzz, high = spoken direction + long strong buzz.
///  - never talk over ourselves: if speech is already playing, skip the new
///    line but still vibrate.
///
/// Speech goes through the app-wide [TtsService] rather than a second
/// FlutterTts instance — two engines running at once talk over each other.
class FeedbackService {
  FeedbackService(this._tts);

  final TtsService _tts;
  bool _hasVibrator = false;

  bool get hasVibrator => _hasVibrator;

  Future<void> initialize() async {
    // `hasVibrator()` is `Future<bool?>` on vibration 1.x and `Future<bool>` on
    // 2.x — comparing to true works on both.
    _hasVibrator = (await Vibration.hasVibrator()) == true;
  }

  /// Start/stop confirmations and error explanations. Always interrupts.
  Future<void> announce(String message) => _tts.interruptAndSpeak(message);

  /// Haptic half of the alert — always runs regardless of `speakAlerts` on
  /// the host controller, since a host screen (e.g. Live Run) that owns
  /// speech for itself should still get the module's vibration language.
  void vibrateFor(ObstacleAlert alert) {
    switch (alert.urgency) {
      case AlertUrgency.none:
        return;
      case AlertUrgency.low:
        _vibrate(duration: 80, amplitude: 60);
        break;
      case AlertUrgency.medium:
        _vibrate(pattern: const [0, 100, 80, 100], amplitude: 150);
        break;
      case AlertUrgency.high:
        _vibrate(duration: 400, amplitude: 255);
        break;
    }
  }

  /// Speech half of the alert — gated by the host controller's `speakAlerts`.
  void speakFor(ObstacleAlert alert) {
    switch (alert.urgency) {
      case AlertUrgency.none:
      case AlertUrgency.low:
        return;
      case AlertUrgency.medium:
        _speak(_word(alert.direction));
        break;
      case AlertUrgency.high:
        _speak('${_word(alert.direction)}, stop');
        break;
    }
  }

  void _speak(String text) {
    if (_tts.isSpeaking) return; // don't stack speech
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
      Vibration.vibrate(pattern: pattern, amplitude: amplitude);
    } else {
      Vibration.vibrate(duration: duration ?? 100, amplitude: amplitude);
    }
  }

  /// Deliberately does NOT stop the TTS engine: [_tts] is the app-wide
  /// singleton from the Provider tree, so stopping it here would cut off
  /// speech belonging to whatever screen comes next.
  Future<void> dispose() async {}
}
