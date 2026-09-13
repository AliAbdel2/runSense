import 'dart:async';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_tts/flutter_tts.dart';

import 'cloud_tts_client.dart';

/// Speaks via ElevenLabs (cloud, much more human-sounding) when an API key
/// is configured — see env.example.json — and transparently falls back to
/// on-device flutter_tts otherwise (no key, offline, a failed request).
/// Callers never see the difference; both paths go through speak()/
/// interruptAndSpeak()/stop().
class TtsService {
  final FlutterTts _tts = FlutterTts();
  final AudioPlayer _player = AudioPlayer();
  final ElevenLabsClient _cloud = ElevenLabsClient();
  bool _speaking = false;

  TtsService() {
    _tts.setVolume(1.0);
    _tts.setPitch(1.0);
    // flutter_tts's speech-rate scale is NOT consistent across platforms.
    // On web its implementation passes the value straight through to the
    // browser's own SpeechSynthesisUtterance.rate, where 1.0 is normal
    // human speaking pace — a flat 0.55 (meant as "0.0 slowest..1.0
    // fastest" per the plugin's own doc comment, tuned for native) landed
    // there as literally 55% speed, which reads as slow and robotic. On
    // Android/iOS the plugin normalizes its own 0.0-1.0 scale so ~0.5
    // already lands near a natural pace. This only matters for the
    // fallback path (no ElevenLabs key, or a failed request).
    _tts.setSpeechRate(kIsWeb ? 0.95 : 0.5);
    _tts.setCompletionHandler(() => _speaking = false);
    _player.onPlayerComplete.listen((_) => _speaking = false);
    _pickNaturalVoice();
  }

  /// Best local voice to fall back to if ElevenLabs isn't configured or a
  /// request fails. Browsers expose their higher-quality voices (Windows
  /// 11's neural "... Online (Natural) ..." voices, Google's network
  /// voices) alongside the OS's flat default SAPI-style voice; this ranks
  /// what's actually installed and picks the least robotic one. Native
  /// platforms (Android/iOS) already ship one good default voice, so this
  /// only runs on web. Best-effort throughout: if voice enumeration fails,
  /// comes back empty, or nothing ranks, the platform default is used.
  Future<void> _pickNaturalVoice() async {
    if (!kIsWeb) return;
    try {
      // Chrome/Edge often report an empty voice list for a moment after
      // page load — the real list only populates once the browser's
      // speechSynthesis backend finishes initializing. Retry briefly
      // instead of accepting a premature empty result.
      List<Map<String, dynamic>> voices = [];
      for (var attempt = 0; attempt < 6 && voices.isEmpty; attempt++) {
        if (attempt > 0) await Future.delayed(const Duration(milliseconds: 300));
        final raw = await _tts.getVoices as List<dynamic>?;
        if (raw == null) continue;
        voices = raw.map((e) => Map<String, dynamic>.from(e as Map)).toList();
      }
      if (voices.isEmpty) return;

      final english =
          voices.where((v) => (v['locale'] as String? ?? '').startsWith('en')).toList();
      final pool = english.isNotEmpty ? english : voices;

      Map<String, dynamic>? pick(bool Function(String name) test) {
        for (final v in pool) {
          if (test((v['name'] as String? ?? '').toLowerCase())) return v;
        }
        return null;
      }

      final chosen = pick((n) => n.contains('natural')) ??
          pick((n) => n.contains('google')) ??
          pick((n) => n.contains('online')) ??
          pool.first;

      final name = chosen['name'] as String? ?? '';
      final locale = chosen['locale'] as String? ?? '';
      if (name.isNotEmpty) {
        await _tts.setVoice({'name': name, 'locale': locale});
      }
    } catch (_) {
      // Fall back to whatever voice the platform already defaulted to.
    }
  }

  bool get isSpeaking => _speaking;

  Future<void> speak(String text) async {
    _speaking = true;
    final audio = await _cloud.synthesize(text);
    if (audio != null) {
      await _player.play(BytesSource(audio));
      return;
    }
    // No key configured, or the ElevenLabs request failed (offline,
    // rate-limited, etc) — still speaks, just via the less natural
    // on-device voice rather than going silent.
    await _tts.speak(text);
  }

  /// Stops whatever is currently playing, then speaks — used for
  /// high-urgency alerts that must interrupt (Live Run screen, checkpoint 4).
  Future<void> interruptAndSpeak(String text) async {
    await stop();
    await speak(text);
  }

  Future<void> stop() async {
    // Only touch the audio player if cloud TTS is actually in play — with
    // no ElevenLabs key configured, play() is never called, and invoking
    // stop() on a player that's never played anything still round-trips
    // through its platform channel for no reason (and, with no channel
    // handler registered, e.g. under `flutter test`, can hang rather than
    // throw — audioplayers doesn't fail fast the way flutter_tts does).
    if (_cloud.isConfigured) {
      await _player.stop();
    }
    await _tts.stop();
    _speaking = false;
  }
}
