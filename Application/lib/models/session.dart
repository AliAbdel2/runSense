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

  const PlannedSession({
    required this.id,
    required this.date,
    required this.type,
    required this.description,
    required this.spokenSummary,
    required this.guideStatus,
    required this.venue,
  });
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
