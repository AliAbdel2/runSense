import 'package:google_mlkit_object_detection/google_mlkit_object_detection.dart';

/// Thin wrapper around ML Kit's on-device object detector.
///
/// Stream mode + tracking gives each object a stable `trackingId` across
/// frames, which is what lets the controller avoid re-alerting on the same
/// obstacle every single frame.
class DetectionService {
  late final ObjectDetector _detector;

  DetectionService() {
    final options = ObjectDetectorOptions(
      mode: DetectionMode.stream, // continuous video
      classifyObjects: true, // coarse label when the model can manage one
      multipleObjects: true, // several obstacles at once
    );
    _detector = ObjectDetector(options: options);
  }

  Future<List<DetectedObject>> detect(InputImage image) =>
      _detector.processImage(image);

  Future<void> dispose() => _detector.close();
}
