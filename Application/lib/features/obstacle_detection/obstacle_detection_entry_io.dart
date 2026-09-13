import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

import '../../services/perception_service.dart';
import '../../services/tts_service.dart';
import 'live_perception_service.dart';

/// True wherever a camera pipeline can actually run (Android / iOS).
const bool obstacleDetectionSupported = true;

PerceptionService createLivePerceptionService(TtsService tts) =>
    LivePerceptionService(tts);

/// Renders the live camera preview for the Live Run screen, or null if the
/// given service isn't a live camera (mock, or not yet initialized).
Widget? buildRunCameraPreview(PerceptionService service) {
  if (service is! LivePerceptionService) return null;
  final camera = service.controller.camera;
  if (!camera.isInitialized) return null;
  return CameraPreview(camera.controller!);
}
