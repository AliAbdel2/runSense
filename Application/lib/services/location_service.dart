import '../models/location_fix.dart';

/// GPS tracking for pace/distance during a run. Not part of the original
/// plan's section 4 interfaces — added ahead of the real camera/GPS work so
/// a LiveLocationService (backed by `geolocator`) drops in as a one-file
/// swap later, same pattern as the other Live*Service seams.
abstract class LocationService {
  /// True once the user has granted location permission.
  Future<bool> requestPermission();

  Stream<LocationFix> positionStream(); // starts/stops with tracking
  void startTracking();
  void stopTracking();
}
