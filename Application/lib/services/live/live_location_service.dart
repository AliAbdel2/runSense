import 'dart:async';

import 'package:geolocator/geolocator.dart';

import '../../models/location_fix.dart';
import '../location_service.dart';

/// Streams real device positions while a run is active.
class LiveLocationService implements LocationService {
  final _controller = StreamController<LocationFix>.broadcast();
  StreamSubscription<Position>? _subscription;

  @override
  Future<bool> requestPermission() async {
    if (!await Geolocator.isLocationServiceEnabled()) return false;

    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    return permission == LocationPermission.whileInUse ||
        permission == LocationPermission.always;
  }

  @override
  Stream<LocationFix> positionStream() => _controller.stream;

  @override
  void startTracking() {
    if (_subscription != null) return;
    const settings = LocationSettings(
      accuracy: LocationAccuracy.high,
      distanceFilter: 2,
    );
    _subscription = Geolocator.getPositionStream(locationSettings: settings)
        .listen(
      (position) {
        if (_controller.isClosed) return;
        _controller.add(LocationFix(
          latitude: position.latitude,
          longitude: position.longitude,
          speedMetersPerSecond: position.speed >= 0 ? position.speed : null,
          accuracyMeters: position.accuracy,
          altitudeMeters: position.altitude,
          ts: position.timestamp,
        ));
      },
      onError: _controller.addError,
    );
  }

  @override
  void stopTracking() {
    final subscription = _subscription;
    _subscription = null;
    unawaited(subscription?.cancel());
  }

  void dispose() {
    stopTracking();
    unawaited(_controller.close());
  }
}
