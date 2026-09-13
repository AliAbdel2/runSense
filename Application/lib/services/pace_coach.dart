import 'dart:math';

import '../models/location_fix.dart';

/// Pure pace-calling logic for a live run: no Flutter imports so it's
/// unit-testable without a widget harness. Consumes [LocationFix]es and
/// decides when to speak a pace cue; never touches TTS directly — its output
/// goes through `RunNarrator.announcePace`.
class PaceCoach {
  PaceCoach({this.targetPaceSecPerKm});

  /// Target pace in seconds/km. Null (e.g. a rest day) disables off-pace
  /// nudges; periodic pace callouts still work.
  final int? targetPaceSecPerKm;

  static const windowSize = 10;
  static const periodicInterval = Duration(seconds: 60);
  static const offPaceRatio = 0.10; // >10% off target
  static const offPaceConsecutive = 3;
  static const offPaceCooldown = Duration(seconds: 45);

  final List<double> _speedWindow = [];
  LocationFix? _lastFix;
  DateTime? _lastPeriodicAt;
  DateTime? _lastOffPaceAt;
  int _fastStreak = 0;
  int _slowStreak = 0;

  /// Feed one location fix in. Returns an utterance to announce, or null.
  String? onFix(LocationFix fix) {
    // Baseline the periodic clock on run start, not on the first fix that
    // happens to carry usable speed — otherwise the first callout could fire
    // immediately instead of after a full interval.
    _lastPeriodicAt ??= fix.ts;

    final speed = _speedFor(fix);
    final previousFix = _lastFix;
    _lastFix = fix;
    if (speed == null || speed <= 0) return null;

    _speedWindow.add(speed);
    if (_speedWindow.length > windowSize) _speedWindow.removeAt(0);
    final smoothedSpeed =
        _speedWindow.reduce((a, b) => a + b) / _speedWindow.length;

    // Don't fire a periodic callout on the very first fix, before any
    // smoothing has happened.
    if (previousFix != null) {
      final periodic = _checkPeriodic(fix.ts, smoothedSpeed);
      if (periodic != null) return periodic;

      return _checkOffPace(fix.ts, smoothedSpeed);
    }
    return null;
  }

  double? _speedFor(LocationFix fix) {
    if (fix.speedMetersPerSecond != null) return fix.speedMetersPerSecond;
    final prev = _lastFix;
    if (prev == null) return null;
    final dtSeconds = fix.ts.difference(prev.ts).inMilliseconds / 1000.0;
    if (dtSeconds <= 0) return null;
    return _haversineMeters(prev, fix) / dtSeconds;
  }

  String? _checkPeriodic(DateTime now, double smoothedSpeed) {
    final last = _lastPeriodicAt;
    if (last != null && now.difference(last) < periodicInterval) return null;
    _lastPeriodicAt = now;
    final paceSecPerKm = (1000 / smoothedSpeed).round();
    return 'Pace, ${formatPaceWords(paceSecPerKm)} per kilometre';
  }

  String? _checkOffPace(DateTime now, double smoothedSpeed) {
    final target = targetPaceSecPerKm;
    if (target == null) return null;

    final cooldownUntil = _lastOffPaceAt?.add(offPaceCooldown);
    if (cooldownUntil != null && now.isBefore(cooldownUntil)) return null;

    final actualPaceSecPerKm = 1000 / smoothedSpeed;
    final ratio = (actualPaceSecPerKm - target) / target;

    if (ratio < -offPaceRatio) {
      // Lower pace number = running faster than target.
      _fastStreak++;
      _slowStreak = 0;
    } else if (ratio > offPaceRatio) {
      _slowStreak++;
      _fastStreak = 0;
    } else {
      _fastStreak = 0;
      _slowStreak = 0;
      return null;
    }

    if (_fastStreak >= offPaceConsecutive) {
      _fastStreak = 0;
      _lastOffPaceAt = now;
      return 'Ease off';
    }
    if (_slowStreak >= offPaceConsecutive) {
      _slowStreak = 0;
      _lastOffPaceAt = now;
      return 'Pick it up';
    }
    return null;
  }

  /// "5:33" spoken as "five thirty-three" (TTS reads raw "5:33" badly).
  static String formatPaceWords(int paceSecPerKm) {
    final minutes = paceSecPerKm ~/ 60;
    final seconds = paceSecPerKm % 60;
    final minutesWord = _wordsForNumber(minutes);
    if (seconds == 0) return '$minutesWord minutes flat';
    if (seconds < 10) return '$minutesWord oh ${_wordsForNumber(seconds)}';
    return '$minutesWord ${_wordsForNumber(seconds)}';
  }

  static const _ones = [
    'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight',
    'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen',
    'sixteen', 'seventeen', 'eighteen', 'nineteen', //
  ];
  static const _tens = [
    '', '', 'twenty', 'thirty', 'forty', 'fifty', //
  ];

  static String _wordsForNumber(int n) {
    if (n < 20) return _ones[n];
    final tensDigit = n ~/ 10;
    final onesDigit = n % 10;
    final tensWord = _tens[tensDigit];
    return onesDigit == 0 ? tensWord : '$tensWord-${_ones[onesDigit]}';
  }

  double _haversineMeters(LocationFix a, LocationFix b) {
    const earthRadiusMeters = 6371000.0;
    final dLat = _degToRad(b.latitude - a.latitude);
    final dLon = _degToRad(b.longitude - a.longitude);
    final lat1 = _degToRad(a.latitude);
    final lat2 = _degToRad(b.latitude);
    final h = sin(dLat / 2) * sin(dLat / 2) +
        sin(dLon / 2) * sin(dLon / 2) * cos(lat1) * cos(lat2);
    return 2 * earthRadiusMeters * atan2(sqrt(h), sqrt(1 - h));
  }

  double _degToRad(double deg) => deg * pi / 180;
}
