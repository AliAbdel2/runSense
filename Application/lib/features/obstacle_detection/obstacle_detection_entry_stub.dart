import 'package:flutter/material.dart';

import '../../services/perception_service.dart';
import '../../services/tts_service.dart';

/// Web build: no camera pipeline. See `obstacle_detection_entry.dart`.
const bool obstacleDetectionSupported = false;

PerceptionService createLivePerceptionService(TtsService tts) =>
    throw UnsupportedError(
      'Camera-based obstacle detection requires Android or iOS. This build '
      'targets the web and must use the mock perception service.',
    );

Widget? buildRunCameraPreview(PerceptionService service) => null;
