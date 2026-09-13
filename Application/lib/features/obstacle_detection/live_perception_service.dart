import 'dart:async';

import '../../models/alert.dart' as app;
import '../../services/perception_service.dart';
import '../../services/tts_service.dart';
import 'models/detected_obstacle.dart';
import 'models/obstacle_alert.dart';
import 'obstacle_detection_controller.dart';

/// The camera pipeline, wearing the app's [PerceptionService] interface.
///
/// This is the seam described in `runsense_flutter_plan.md` section 10: the
/// module keeps its own internal alert type and this class translates it into
/// `lib/models/alert.dart`'s [app.ObstacleAlert] on the way out, so the Live
/// Run screen (and anything else downstream) is unchanged whether alerts come
/// from [MockPerceptionService] or from a real camera.
///
/// Speech is left to the host screen — [ObstacleDetectionController] is
/// constructed with `speakAlerts: false` so the module and the Live Run screen
/// don't both talk about the same obstacle.
class LivePerceptionService implements PerceptionService {
  LivePerceptionService(TtsService tts)
      : _controller =
            ObstacleDetectionController(tts: tts, speakAlerts: false) {
    _sub = _controller.alerts.listen((a) {
      if (!_out.isClosed) _out.add(_translate(a));
    });
  }

  final ObstacleDetectionController _controller;
  final _out = StreamController<app.ObstacleAlert>.broadcast();
  late final StreamSubscription<ObstacleAlert> _sub;

  /// Exposed so a host screen can render the camera preview if it wants one.
  ObstacleDetectionController get controller => _controller;

  @override
  Stream<app.ObstacleAlert> alertStream() => _out.stream;

  /// Named `startSimulation` only because that is what the interface calls it
  /// (it was written against the mock). Here it starts the real camera.
  @override
  void startSimulation() {
    unawaited(_controller.start());
  }

  @override
  void stopSimulation() {
    unawaited(_controller.stop());
  }

  Future<void> dispose() async {
    await _sub.cancel();
    await _out.close();
    _controller.dispose();
  }

  app.ObstacleAlert _translate(ObstacleAlert a) {
    final zone = _zone(a.direction);
    final distance = _distance(a.urgency);
    final tier = _tier(a.urgency);
    return app.ObstacleAlert(
      objectClass: a.label,
      zone: zone,
      distance: distance,
      tier: tier,
      utterance: _utterance(a.label, zone, tier),
      latencyMs: a.latencyMs,
      ts: DateTime.now(),
    );
  }

  app.Zone _zone(ObstacleDirection d) {
    switch (d) {
      case ObstacleDirection.left:
        return app.Zone.left;
      case ObstacleDirection.center:
        return app.Zone.center;
      case ObstacleDirection.right:
        return app.Zone.right;
    }
  }

  app.Distance _distance(AlertUrgency u) {
    switch (u) {
      case AlertUrgency.high:
        return app.Distance.near;
      case AlertUrgency.medium:
        return app.Distance.mid;
      case AlertUrgency.low:
      case AlertUrgency.none:
        return app.Distance.far;
    }
  }

  app.AlertTier _tier(AlertUrgency u) {
    switch (u) {
      case AlertUrgency.high:
        return app.AlertTier.danger;
      case AlertUrgency.medium:
        return app.AlertTier.warning;
      case AlertUrgency.low:
      case AlertUrgency.none:
        return app.AlertTier.notice;
    }
  }

  /// Matches the phrasing of MockData.alertScript so the demo sounds the same
  /// whichever service is driving it: "Bike far right" / "Person left" /
  /// "Stop - person ahead".
  String _utterance(String label, app.Zone zone, app.AlertTier tier) {
    final where = switch (zone) {
      app.Zone.left => 'left',
      app.Zone.center => 'ahead',
      app.Zone.right => 'right',
    };
    final name = label.isEmpty
        ? 'Obstacle'
        : label[0].toUpperCase() + label.substring(1);
    switch (tier) {
      case app.AlertTier.danger:
        return 'Stop - ${name.toLowerCase()} $where';
      case app.AlertTier.warning:
        return '$name $where';
      case app.AlertTier.notice:
        return '$name far $where';
    }
  }
}
