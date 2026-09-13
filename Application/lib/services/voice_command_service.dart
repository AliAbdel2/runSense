import 'dart:async';

import 'package:speech_to_text/speech_to_text.dart';

/// Thin wrapper around speech_to_text, mirroring TtsService: real, not
/// mocked. A blind runner may never find the START RUN button, so the
/// briefing screen uses this to accept a spoken "start" as well as a tap —
/// see coach_briefing_screen.dart.
///
/// listen() on the underlying plugin only resolves once the session has
/// *started*, not once it ends — the session's actual end is reported later
/// through the onStatus callback passed to initialize(). listenForPhrase
/// bridges that back into a single awaitable Future via [_sessionEnded].
class VoiceCommandService {
  final SpeechToText _speech = SpeechToText();
  bool? _available;
  Completer<void>? _sessionEnded;

  Future<bool> _ensureInitialized() async {
    if (_available != null) return _available!;
    try {
      _available = await _speech.initialize(
        onStatus: (status) {
          if (status == 'notListening' || status == 'done') {
            _sessionEnded?.complete();
          }
        },
      );
    } catch (_) {
      _available = false;
    }
    return _available!;
  }

  /// Listens until the recognized words contain one of [triggerPhrases]
  /// (case-insensitive) or [timeout] elapses, then calls [onMatch] at most
  /// once. Returns false immediately, without calling [onMatch], if the
  /// mic/plugin/permission isn't available — callers must always leave a
  /// manual fallback for that case, and must not busy-retry on a `false`
  /// return (there's nothing that will make it become available mid-screen).
  /// A `true` return means a full listen session ran (matched or timed out).
  Future<bool> listenForPhrase({
    required List<String> triggerPhrases,
    required void Function() onMatch,
    Duration timeout = const Duration(seconds: 20),
  }) async {
    if (!await _ensureInitialized()) return false;

    var matched = false;
    final sessionEnded = Completer<void>();
    _sessionEnded = sessionEnded;

    try {
      await _speech.listen(
        onResult: (result) {
          if (matched) return;
          final heard = result.recognizedWords.toLowerCase();
          final heardWords = heard.split(RegExp(r'\s+')).toSet();
          final hit = triggerPhrases.any((phrase) => phrase.contains(' ')
              ? heard.contains(phrase)
              : heardWords.contains(phrase));
          if (hit) {
            matched = true;
            _speech.stop();
            onMatch();
          }
        },
        listenFor: timeout,
        pauseFor: const Duration(seconds: 5),
        partialResults: true,
      );
    } catch (_) {
      return true;
    }

    // Safety net above the plugin's own timeout, in case onStatus never
    // fires 'notListening'/'done' on some platform/engine.
    await sessionEnded.future
        .timeout(timeout + const Duration(seconds: 5), onTimeout: () {});
    return true;
  }

  Future<void> stop() async {
    try {
      await _speech.stop();
    } catch (_) {}
  }
}
