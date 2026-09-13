import 'package:intl/intl.dart';

import '../../models/alert.dart';
import '../../models/athlete.dart';
import '../../models/guide_status.dart';
import '../../models/session.dart';

/// All canned data for the demo lives here. Edit this file, not the mock
/// services, when tuning the demo (timings, wording, the persona's week).
class MockData {
  static const athlete = Athlete(
    id: 'sara-1',
    name: 'Sara',
    guideDays: ['Tue', 'Sat'],
    preferredVenue: 'track',
  );

  /// Next occurrence of [weekday] (1=Mon..7=Sun) on/after today, as an ISO date.
  static String _isoDateForNextWeekday(int weekday) {
    var date = DateTime.now();
    while (date.weekday != weekday) {
      date = date.add(const Duration(days: 1));
    }
    return DateFormat('yyyy-MM-dd').format(date);
  }

  static List<PlannedSession> baseWeek() => [
        PlannedSession(
          id: 'mon-rest',
          date: _isoDateForNextWeekday(DateTime.monday),
          type: SessionType.rest,
          description: 'Rest day',
          spokenSummary: 'Today is a rest day. No running scheduled.',
          guideStatus: GuideStatus.notNeeded,
          venue: 'n/a',
        ),
        PlannedSession(
          id: 'tue-hard',
          date: _isoDateForNextWeekday(DateTime.tuesday),
          type: SessionType.hard,
          description: '4x800m intervals',
          spokenSummary:
              'Today is 4 times 800 meter intervals at the track. Your guide is confirmed.',
          guideStatus: GuideStatus.accepted,
          venue: 'track',
        ),
        PlannedSession(
          id: 'wed-rest',
          date: _isoDateForNextWeekday(DateTime.wednesday),
          type: SessionType.rest,
          description: 'Rest day',
          spokenSummary: 'Today is a rest day. No running scheduled.',
          guideStatus: GuideStatus.notNeeded,
          venue: 'n/a',
        ),
        PlannedSession(
          id: 'thu-easy',
          date: _isoDateForNextWeekday(DateTime.thursday),
          type: SessionType.easy,
          description: '5k easy run',
          spokenSummary: 'Today is a 5 kilometer easy run outdoors. No guide needed.',
          guideStatus: GuideStatus.notNeeded,
          venue: 'outdoor',
        ),
        PlannedSession(
          id: 'fri-rest',
          date: _isoDateForNextWeekday(DateTime.friday),
          type: SessionType.rest,
          description: 'Rest day',
          spokenSummary: 'Today is a rest day. No running scheduled.',
          guideStatus: GuideStatus.notNeeded,
          venue: 'n/a',
        ),
        PlannedSession(
          id: 'sat-long',
          date: _isoDateForNextWeekday(DateTime.saturday),
          type: SessionType.longRun,
          description: '12k long run',
          spokenSummary:
              'Today is a 12 kilometer long run outdoors. Your guide is confirmed.',
          guideStatus: GuideStatus.accepted,
          venue: 'outdoor',
        ),
        PlannedSession(
          id: 'sun-rest',
          date: _isoDateForNextWeekday(DateTime.sunday),
          type: SessionType.rest,
          description: 'Rest day',
          spokenSummary: 'Today is a rest day. No running scheduled.',
          guideStatus: GuideStatus.notNeeded,
          venue: 'n/a',
        ),
      ];

  /// Returned by requestReplan() — Tuesday's guide fell through, so Thursday's
  /// easy run is bumped up to cover some of the missed intervals.
  static List<PlannedSession> adaptedWeek() {
    final week = baseWeek();
    return [
      for (final s in week)
        if (s.id == 'tue-hard')
          PlannedSession(
            id: s.id,
            date: s.date,
            type: s.type,
            description: '${s.description} (guide cancelled)',
            spokenSummary:
                'Your guide cancelled today\'s intervals. This session is now marked pending.',
            guideStatus: GuideStatus.pending,
            venue: s.venue,
          )
        else if (s.id == 'thu-easy')
          PlannedSession(
            id: s.id,
            date: s.date,
            type: s.type,
            description: '7k easy run (extended)',
            spokenSummary:
                'Thursday was extended to 7 kilometers because Tuesday was cut short.',
            guideStatus: s.guideStatus,
            venue: s.venue,
          )
        else
          s,
    ];
  }

  /// Fixed-timing alert script for the Live Run demo. Offsets are from the
  /// moment simulation starts. Edit freely before a demo run.
  static final List<ScriptedAlertCue> alertScript = [
    ScriptedAlertCue(
      offset: const Duration(seconds: 2),
      objectClass: 'bicycle',
      zone: Zone.right,
      distance: Distance.far,
      tier: AlertTier.notice,
      utterance: 'Bike far right',
    ),
    ScriptedAlertCue(
      offset: const Duration(seconds: 6),
      objectClass: 'person',
      zone: Zone.left,
      distance: Distance.mid,
      tier: AlertTier.warning,
      utterance: 'Person left',
    ),
    ScriptedAlertCue(
      offset: const Duration(seconds: 9),
      objectClass: 'person',
      zone: Zone.center,
      distance: Distance.near,
      tier: AlertTier.danger,
      utterance: 'Stop - person ahead',
    ),
  ];
}

/// One entry in the scripted alert timeline (see [MockData.alertScript]).
class ScriptedAlertCue {
  final Duration offset;
  final String objectClass;
  final Zone zone;
  final Distance distance;
  final AlertTier tier;
  final String utterance;

  const ScriptedAlertCue({
    required this.offset,
    required this.objectClass,
    required this.zone,
    required this.distance,
    required this.tier,
    required this.utterance,
  });
}
