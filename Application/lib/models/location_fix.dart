/// A single GPS fix, shaped like what geolocator's `Position` gives back —
/// kept as our own small model (not a re-export of geolocator's type) so
/// screens never depend on that package directly, same reasoning as
/// ObstacleAlert not being a raw ML Kit type.
class LocationFix {
  final double latitude;
  final double longitude;
  final double? speedMetersPerSecond;
  final double? accuracyMeters;
  final double? altitudeMeters;
  final DateTime ts;

  const LocationFix({
    required this.latitude,
    required this.longitude,
    this.speedMetersPerSecond,
    this.accuracyMeters,
    this.altitudeMeters,
    required this.ts,
  });
}
