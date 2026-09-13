import '../models/location_fix.dart';
import '../models/session.dart';

abstract class SessionService {
  Future<CompletedSession> startSession(String plannedSessionId);
  Future<void> addLocationSample(String sessionId, LocationFix fix);
  Future<CompletedSession> endSession(String sessionId);
}
