import '../models/session.dart';

abstract class PlanService {
  Future<List<PlannedSession>> getWeekPlan(String athleteId);
  Future<void> requestReplan(String reason); // "guide cancelled" etc.
}
