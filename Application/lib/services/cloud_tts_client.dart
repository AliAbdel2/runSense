import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

/// Thin client for ElevenLabs' text-to-speech REST API. Returns `null`
/// (never throws) whenever synthesis isn't available — no key configured,
/// a network error, a non-200 response — so `TtsService` can fall back to
/// the on-device `flutter_tts` voice without any special-casing at the call
/// site.
///
/// The API key is supplied at build/run time via
/// `--dart-define-from-file=env.json` (see env.example.json at the repo
/// root) — never hardcoded or committed.
class ElevenLabsClient {
  static const _apiKey = String.fromEnvironment('ELEVENLABS_API_KEY');

  // "Sarah" — mature, reassuring, confident; a good fit for a running
  // coach that also has to deliver calm safety alerts. Deliberately NOT
  // "Rachel" (id 21m00Tcm4TlvDq8ikWAM): that's one of ElevenLabs' older
  // "voice library" voices, which their free tier blocks from API use
  // entirely (402 payment_required) even with a valid key — confirmed by
  // testing directly against the API. "Sarah" is one of this account's own
  // usable premade voices. Overridable via dart-define if a different one
  // reads better for this app.
  static const _voiceId =
      String.fromEnvironment('ELEVENLABS_VOICE_ID', defaultValue: 'EXAVITQu4vr4xnSDxMaL');

  bool get isConfigured => _apiKey.isNotEmpty;

  Future<Uint8List?> synthesize(String text) async {
    if (!isConfigured) return null;
    try {
      final response = await http
          .post(
            Uri.parse('https://api.elevenlabs.io/v1/text-to-speech/$_voiceId'),
            headers: {
              'xi-api-key': _apiKey,
              'Content-Type': 'application/json',
              'Accept': 'audio/mpeg',
            },
            body: jsonEncode({'text': text, 'model_id': 'eleven_turbo_v2_5'}),
          )
          .timeout(const Duration(seconds: 8));
      if (response.statusCode != 200) return null;
      return response.bodyBytes;
    } catch (_) {
      return null;
    }
  }
}
