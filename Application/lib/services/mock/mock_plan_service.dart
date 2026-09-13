import '../../models/session.dart';
import '../plan_service.dart';
import 'mock_data.dart';

class MockPlanService implements PlanService {
  List<PlannedSession> _currentWeek = MockData.baseWeek();

  @override
  Future<List<PlannedSession>> getWeekPlan(String athleteId) async {
    await Future.delayed(const Duration(milliseconds: 300));
    return _currentWeek;
  }

  @override
  Future<void> requestReplan(String reason) async {
    await Future.delayed(const Duration(milliseconds: 300));
    _currentWeek = MockData.adaptedWeek();
  }
}
