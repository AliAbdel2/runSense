import 'package:flutter_tts/flutter_tts.dart';

/// Thin wrapper around flutter_tts. Real, not mocked — see plan section 4.
class TtsService {
  final FlutterTts _tts = FlutterTts();

  /// When we stop believing an in-flight utterance, even with no callback.
  DateTime? _speakingUntil;

  /// Longest we ever assume a completion callback is still coming.
  ///
  /// flutter_tts drops completion callbacks on some platforms/engines, and
  /// callers skip speech while [isSpeaking] — so without this cap one missed
  /// callback would silence every later alert for the rest of the run.
  static const _maxUtterance = Duration(seconds: 5);

  TtsService() {
    _tts.setSpeechRate(0.55);
    _tts.setVolume(1.0);
    _tts.setCompletionHandler(_finished);
    _tts.setCancelHandler(_finished);
    _tts.setErrorHandler((_) => _finished());
  }

  void _finished() => _speakingUntil = null;

  bool get isSpeaking {
    final until = _speakingUntil;
    if (until == null) return false;
    if (!DateTime.now().isBefore(until)) {
      _speakingUntil = null; // callback never arrived — assume it finished
      return false;
    }
    return true;
  }

  Future<void> speak(String text) async {
    _speakingUntil = DateTime.now().add(_maxUtterance);
    await _tts.speak(text);
  }

  /// Stops whatever is currently playing, then speaks — used for
  /// high-urgency alerts that must interrupt (Live Run screen, checkpoint 4).
  Future<void> interruptAndSpeak(String text) async {
    await _tts.stop();
    _speakingUntil = DateTime.now().add(_maxUtterance);
    await _tts.speak(text);
  }

  Future<void> stop() async {
    await _tts.stop();
    _speakingUntil = null;
  }
}
