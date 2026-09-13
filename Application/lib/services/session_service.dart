import '../models/session.dart';

abstract class SessionService {
  Future<CompletedSession> startSession(String plannedSessionId);
  Future<void> endSession(String sessionId);
}
