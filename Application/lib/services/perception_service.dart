import '../models/alert.dart';

abstract class PerceptionService {
  Stream<ObstacleAlert> alertStream(); // starts/stops with session
  void startSimulation();
  void stopSimulation();
  Future<void> dispose();
}
