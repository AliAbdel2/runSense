import 'guide_status.dart';

enum SessionType { easy, hard, longRun, rest }

class PlannedSession {
  final String id;
  final String date; // ISO date
  final SessionType type;
  final String description; // e.g. "4x800m intervals"
  final String spokenSummary; // <25 words, TTS-ready
  final GuideStatus guideStatus;
  final String venue;
  final int? targetPaceSecPerKm;

  const PlannedSession({
    required this.id,
    required this.date,
    required this.type,
    required this.description,
    required this.spokenSummary,
    required this.guideStatus,
    required this.venue,
    this.targetPaceSecPerKm,
  });

  /// Fallback pace target when the session doesn't set one explicitly.
  int? get effectiveTargetPaceSecPerKm {
    if (targetPaceSecPerKm != null) return targetPaceSecPerKm;
    switch (type) {
      case SessionType.hard:
        return 300;
      case SessionType.easy:
        return 390;
      case SessionType.longRun:
        return 420;
      case SessionType.rest:
        return null;
    }
  }
}

class CompletedSession {
  final String sessionId;
  final double actualKm;
  final Duration duration;
  final int alertCount;
  final String? adaptationNote; // "Thu reduced because Tue was cut short"

  const CompletedSession({
    required this.sessionId,
    required this.actualKm,
    required this.duration,
    required this.alertCount,
    this.adaptationNote,
  });
}
