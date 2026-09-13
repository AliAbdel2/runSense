import 'package:flutter/services.dart';

import '../models/alert.dart';
import 'tts_service.dart';

/// Single owner of run-time speech. Three sources — obstacle alerts, pace
/// cues, and (implicitly) whatever else might want to talk — compete for one
/// TTS engine; without an arbiter a pace callout can step on "Stop - person
/// ahead", which is the one failure that matters here.
class RunNarrator {
  RunNarrator(this._tts);

  final TtsService _tts;

  static const _quietAfterObstacle = Duration(seconds: 3);

  DateTime? _lastObstacleAt;

  void announceObstacle(ObstacleAlert alert) {
    _lastObstacleAt = DateTime.now();
    if (alert.tier == AlertTier.danger) {
      HapticFeedback.heavyImpact();
      _tts.interruptAndSpeak(alert.utterance);
      return;
    }
    if (_tts.isSpeaking) return;
    _tts.speak(alert.utterance);
  }

  /// State-change announcements (e.g. "Obstacle detection paused") that
  /// aren't tied to a specific alert. Never interrupts, same as a low-tier
  /// obstacle notice.
  void announceSystem(String utterance) {
    if (_tts.isSpeaking) return;
    _tts.speak(utterance);
  }

  void announcePace(String utterance) {
    if (_tts.isSpeaking) return;
    final last = _lastObstacleAt;
    if (last != null && DateTime.now().difference(last) < _quietAfterObstacle) {
      return;
    }
    _tts.speak(utterance);
  }
}
