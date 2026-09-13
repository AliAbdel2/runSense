import 'dart:async';

import '../../models/location_fix.dart';
import '../location_service.dart';

/// Emits a fixed, gently-moving fake path so anything wired to
/// LocationService later (pace/distance on Live Run, an end-of-session
/// summary) has something to render before a real GPS integration exists.
class MockLocationService implements LocationService {
  static const _start = (lat: 40.7128, lon: -74.0060); // arbitrary demo origin

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
      _controller.add(LocationFix(
        latitude: _start.lat + _tick * 0.00005,
        longitude: _start.lon + _tick * 0.00003,
        speedMetersPerSecond: 3.0,
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
