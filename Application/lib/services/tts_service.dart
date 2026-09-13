import 'package:flutter_tts/flutter_tts.dart';

/// Thin wrapper around flutter_tts. Real, not mocked — see plan section 4.
class TtsService {
  final FlutterTts _tts = FlutterTts();
  bool _speaking = false;

  TtsService() {
    _tts.setSpeechRate(0.55);
    _tts.setVolume(1.0);
    _tts.setCompletionHandler(() => _speaking = false);
  }

  bool get isSpeaking => _speaking;

  Future<void> speak(String text) async {
    _speaking = true;
    await _tts.speak(text);
  }

  /// Stops whatever is currently playing, then speaks — used for
  /// high-urgency alerts that must interrupt (Live Run screen, checkpoint 4).
  Future<void> interruptAndSpeak(String text) async {
    await _tts.stop();
    _speaking = true;
    await _tts.speak(text);
  }

  Future<void> stop() async {
    await _tts.stop();
    _speaking = false;
  }
}
