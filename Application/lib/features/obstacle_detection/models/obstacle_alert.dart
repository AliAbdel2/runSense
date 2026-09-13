import 'detected_obstacle.dart';

enum AlertUrgency { none, low, medium, high }

/// The module's INTERNAL alert representation.
///
/// Deliberately NOT the same class as `lib/models/alert.dart`'s `ObstacleAlert`
/// (objectClass/zone/distance/tier/utterance) — see `runsense_flutter_plan.md`
/// section 10. `LivePerceptionService` translates between the two at the
/// boundary, so the rest of the app never sees this type.
class ObstacleAlert {
  final ObstacleDirection direction;
  final AlertUrgency urgency;
  final int? trackingId;
  final String label;

  /// Milliseconds from receiving the camera frame to having this alert ready.
  /// Carried through to `lib/models/alert.dart`'s ObstacleAlert.latencyMs.
  final int latencyMs;

  const ObstacleAlert({
    required this.direction,
    required this.urgency,
    required this.trackingId,
    this.label = 'obstacle',
    this.latencyMs = 0,
  });
}
