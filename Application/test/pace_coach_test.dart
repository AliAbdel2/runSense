import 'package:flutter_test/flutter_test.dart';
import 'package:runsense/models/location_fix.dart';
import 'package:runsense/services/pace_coach.dart';

LocationFix _fix(DateTime ts, double speed) => LocationFix(
      latitude: 0,
      longitude: 0,
      speedMetersPerSecond: speed,
      ts: ts,
    );

void main() {
  group('PaceCoach.formatPaceWords', () {
    test('spells minutes and seconds as words', () {
      expect(PaceCoach.formatPaceWords(333), 'five thirty-three');
    });

    test('spells a flat minute with no seconds', () {
      expect(PaceCoach.formatPaceWords(300), 'five minutes flat');
    });

    test('adds "oh" before single-digit seconds', () {
      expect(PaceCoach.formatPaceWords(305), 'five oh five');
    });
  });

  group('PaceCoach.onFix periodic callouts', () {
    test('emits a pace callout roughly every 60 seconds', () {
      final coach = PaceCoach(targetPaceSecPerKm: 300);
      final start = DateTime(2024, 1, 1);
      var periodicCount = 0;
      for (var i = 0; i <= 125; i++) {
        final result = coach.onFix(_fix(start.add(Duration(seconds: i)), 3.33));
        if (result != null && result.startsWith('Pace,')) periodicCount++;
      }
      // ~125s of steady pace should cross the 60s boundary about twice.
      expect(periodicCount, 2);
    });
  });

  group('PaceCoach.onFix off-pace nudges', () {
    test('nudges "Ease off" after 3 consecutive too-fast fixes', () {
      final coach = PaceCoach(targetPaceSecPerKm: 300); // target ~3.33 m/s
      final start = DateTime(2024, 1, 1);
      String? nudge;
      for (var i = 0; i < 12; i++) {
        final result =
            coach.onFix(_fix(start.add(Duration(seconds: i)), 5.0)); // faster
        if (result == 'Ease off') nudge = result;
      }
      expect(nudge, 'Ease off');
    });

    test('nudges "Pick it up" after 3 consecutive too-slow fixes', () {
      final coach = PaceCoach(targetPaceSecPerKm: 300);
      final start = DateTime(2024, 1, 1);
      String? nudge;
      for (var i = 0; i < 12; i++) {
        final result =
            coach.onFix(_fix(start.add(Duration(seconds: i)), 2.0)); // slower
        if (result == 'Pick it up') nudge = result;
      }
      expect(nudge, 'Pick it up');
    });

    test('applies a cooldown so it does not nag', () {
      final coach = PaceCoach(targetPaceSecPerKm: 300);
      final start = DateTime(2024, 1, 1);
      var nudgeCount = 0;
      for (var i = 0; i < 20; i++) {
        final result = coach.onFix(_fix(start.add(Duration(seconds: i)), 5.0));
        if (result == 'Ease off') nudgeCount++;
      }
      // 20s is well inside the 45s cooldown, so only the first nudge fires.
      expect(nudgeCount, 1);
    });

    test('never nudges when there is no target pace', () {
      final coach = PaceCoach(targetPaceSecPerKm: null);
      final start = DateTime(2024, 1, 1);
      for (var i = 0; i < 12; i++) {
        final result = coach.onFix(_fix(start.add(Duration(seconds: i)), 5.0));
        expect(result == 'Ease off' || result == 'Pick it up', isFalse);
      }
    });
  });
}
