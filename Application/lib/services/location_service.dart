import '../models/location_fix.dart';

/// GPS tracking for pace/distance during a run. The live implementation uses
/// `geolocator`; the mock remains available for deterministic widget tests.
abstract class LocationService {
  /// True once the user has granted location permission.
  Future<bool> requestPermission();

  Stream<LocationFix> positionStream(); // starts/stops with tracking
  void startTracking();
  void stopTracking();
}
