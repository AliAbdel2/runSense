import 'dart:async';

import '../../models/alert.dart';
import '../perception_service.dart';
import 'mock_data.dart';

/// Emits a fixed, timed sequence of alerts (see MockData.alertScript) so the
/// Live Run demo plays out identically every rehearsal. Then goes silent.
class MockPerceptionService implements PerceptionService {
  final _controller = StreamController<ObstacleAlert>.broadcast();
  final List<Timer> _timers = [];

  @override
  Stream<ObstacleAlert> alertStream() => _controller.stream;

  @override
  void startSimulation() {
    stopSimulation();
    for (final cue in MockData.alertScript) {
      _timers.add(Timer(cue.offset, () {
        if (_controller.isClosed) return;
        _controller.add(ObstacleAlert(
          objectClass: cue.objectClass,
          zone: cue.zone,
          distance: cue.distance,
          tier: cue.tier,
          utterance: cue.utterance,
          latencyMs: 0,
          ts: DateTime.now(),
        ));
      }));
    }
  }

  @override
  void stopSimulation() {
    for (final t in _timers) {
      t.cancel();
    }
    _timers.clear();
  }

  void dispose() {
    stopSimulation();
    _controller.close();
  }
}
