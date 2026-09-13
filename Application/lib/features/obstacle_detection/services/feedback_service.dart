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

  Future<void> deliver(ObstacleAlert alert) async {
    switch (alert.urgency) {
      case AlertUrgency.none:
        return;
      case AlertUrgency.low:
        _vibrate(duration: 80, amplitude: 60);
        break;
      case AlertUrgency.medium:
        _vibrate(pattern: const [0, 100, 80, 100], amplitude: 150);
        _speak(_word(alert.direction));
        break;
      case AlertUrgency.high:
        _vibrate(duration: 400, amplitude: 255);
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

  Future<void> dispose() => _tts.stop();
}
