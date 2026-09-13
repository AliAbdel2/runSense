/// Platform-guarded entry point for the obstacle-detection module.
///
/// Everything under `features/obstacle_detection/` (and `google_mlkit_commons`)
/// imports `dart:io`, which is a COMPILE error on the web — so a single import
/// chain from `main.dart` into this module would break `flutter build web`, and
/// the demo currently runs in Chrome. Import THIS file instead of the screen or
/// the service directly: on web it resolves to inert stubs, on Android/iOS to
/// the real thing.
library;

export 'obstacle_detection_entry_stub.dart'
    if (dart.library.io) 'obstacle_detection_entry_io.dart';
