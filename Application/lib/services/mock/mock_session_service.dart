import '../../models/location_fix.dart';
import '../../models/session.dart';
import '../session_service.dart';

class MockSessionService implements SessionService {
  /// Set once endSession() resolves. Not part of the SessionService contract
  /// (which returns void from endSession) — the Live Run / summary screen can
  /// read this to show the "Thu reduced because Tue was cut short" moment.
  CompletedSession? lastCompleted;

  @override
  Future<CompletedSession> startSession(String plannedSessionId) async {
    await Future.delayed(const Duration(milliseconds: 300));
    return CompletedSession(
      sessionId: plannedSessionId,
      actualKm: 0.0,
      duration: Duration.zero,
      alertCount: 0,
    );
  }

  @override
  Future<void> addLocationSample(String sessionId, LocationFix fix) async {}

  @override
  Future<CompletedSession> endSession(String sessionId) async {
    await Future.delayed(const Duration(milliseconds: 500));
    lastCompleted = CompletedSession(
      sessionId: sessionId,
      actualKm: 6.4,
      duration: const Duration(minutes: 32),
      alertCount: 3,
      adaptationNote: 'Thu reduced because Tue was cut short',
    );
    return lastCompleted!;
  }
}
