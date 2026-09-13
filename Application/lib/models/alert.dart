enum AlertTier { danger, warning, notice }

enum Zone { left, center, right }

enum Distance { near, mid, far }

class ObstacleAlert {
  final String objectClass; // "person", "bicycle", ...
  final Zone zone;
  final Distance distance;
  final AlertTier tier;
  final String utterance; // "Stop - person ahead"
  final int latencyMs;
  final DateTime ts;

  const ObstacleAlert({
    required this.objectClass,
    required this.zone,
    required this.distance,
    required this.tier,
    required this.utterance,
    required this.latencyMs,
    required this.ts,
  });
}
