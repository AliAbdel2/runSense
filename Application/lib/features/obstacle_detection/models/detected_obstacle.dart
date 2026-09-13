import 'dart:ui';

/// Which third of the frame an obstacle sits in.
enum ObstacleDirection { left, center, right }

/// One obstacle as the pipeline sees it, after the proximity heuristic has run.
///
/// [proximity] is 0.0 (far) .. 1.0 (very close). For Phase 1 it is the bounding
/// box's height as a fraction of the frame height — a bigger box means a nearer
/// object. Phase 2 replaces the source of this number with real depth in metres
/// (module plan §11); nothing downstream changes.
class DetectedObstacle {
  final int? trackingId; // stable id across frames (may be null)
  final Rect boundingBox; // in image coordinates
  final ObstacleDirection direction;
  final double proximity;
  final String label; // coarse ML Kit class, or 'obstacle' when unclassified

  const DetectedObstacle({
    required this.trackingId,
    required this.boundingBox,
    required this.direction,
    required this.proximity,
    this.label = 'obstacle',
  });
}
