import 'dart:async';
import 'dart:math';

import '../../models/location_fix.dart';
import '../location_service.dart';

/// Emits a fixed, gently-moving fake path so anything wired to
/// LocationService later (pace/distance on Live Run, an end-of-session
/// summary) has something to render before a real GPS integration exists.
class MockLocationService implements LocationService {
  static const _start = (lat: 40.7128, lon: -74.0060); // arbitrary demo origin

  // Sinusoidal drift (roughly 2.4-3.6 m/s, period ~40s) instead of a flat
  // 3.0 m/s — a constant speed can never trip PaceCoach's off-pace branch,
  // which would make that half of the pace-cue feature undemonstrable.
  static const _baseSpeed = 3.0;
  static const _speedAmplitude = 0.6;
  static const _periodSeconds = 40;

  final _controller = StreamController<LocationFix>.broadcast();
  Timer? _timer;
  int _tick = 0;

  @override
  Future<bool> requestPermission() async => true;

  @override
  Stream<LocationFix> positionStream() => _controller.stream;

  @override
  void startTracking() {
    stopTracking();
    _tick = 0;
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (_controller.isClosed) return;
      _tick++;
      final speed = _baseSpeed +
          _speedAmplitude * sin(2 * pi * _tick / _periodSeconds);
      _controller.add(LocationFix(
        latitude: _start.lat + _tick * 0.00005,
        longitude: _start.lon + _tick * 0.00003,
        speedMetersPerSecond: speed,
        ts: DateTime.now(),
      ));
    });
  }

  @override
  void stopTracking() {
    _timer?.cancel();
    _timer = null;
  }

  void dispose() {
    stopTracking();
    _controller.close();
  }
}
