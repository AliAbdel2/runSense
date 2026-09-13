import 'dart:convert';

import 'package:http/http.dart' as http;

import '../../models/location_fix.dart';
import '../../models/session.dart';
import '../api_config.dart';
import '../session_service.dart';

/// Persists live-run lifecycle and GPS samples through /v1/sessions.
class LiveSessionService implements SessionService {
  LiveSessionService({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;
  Future<void> _sampleTail = Future<void>.value();

  @override
  Future<CompletedSession> startSession(String plannedSessionId) async {
    final response = await _client.post(
      Uri.parse('$apiBaseUrl/v1/sessions'),
      headers: apiJsonHeaders(),
      body: jsonEncode({
        'name': 'RunSense session $plannedSessionId',
        'sport_type': 'Run',
      }),
    );
    final body = _decode(response, expectedStatus: 201);
    return _completed(body);
  }

  @override
  Future<void> addLocationSample(String sessionId, LocationFix fix) {
    final operation = _sampleTail.then((_) async {
      final response = await _client.post(
        Uri.parse('$apiBaseUrl/v1/sessions/$sessionId/samples'),
        headers: apiJsonHeaders(),
        body: jsonEncode({
          'samples': [
            {
              'timestamp': fix.ts.toUtc().toIso8601String(),
              'latitude': fix.latitude,
              'longitude': fix.longitude,
              'accuracy_m': fix.accuracyMeters ?? 10.0,
              if (fix.altitudeMeters != null)
                'altitude_m': fix.altitudeMeters,
            },
          ],
        }),
      );
      _decode(response, expectedStatus: 200);
    });
    _sampleTail = operation.catchError((_) {});
    return operation;
  }

  @override
  Future<CompletedSession> endSession(String sessionId) async {
    await _sampleTail;
    final response = await _client.post(
      Uri.parse('$apiBaseUrl/v1/sessions/$sessionId/finish'),
      headers: apiJsonHeaders(),
      body: '{}',
    );
    return _completed(_decode(response, expectedStatus: 200));
  }

  Map<String, dynamic> _decode(
    http.Response response, {
    required int expectedStatus,
  }) {
    if (response.statusCode != expectedStatus) {
      throw Exception(
        'Session request failed (${response.statusCode}): ${response.body}',
      );
    }
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  CompletedSession _completed(Map<String, dynamic> body) {
    return CompletedSession(
      sessionId: body['session_id'] as String,
      actualKm: ((body['distance_m'] as num?) ?? 0).toDouble() / 1000,
      duration: Duration(
        milliseconds:
            ((((body['active_elapsed_seconds'] as num?) ?? 0).toDouble()) *
                    1000)
                .round(),
      ),
      alertCount: 0,
    );
  }

  void dispose() => _client.close();
}
