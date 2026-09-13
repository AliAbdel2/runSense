import 'package:flutter/material.dart';

import '../../services/perception_service.dart';
import '../../services/tts_service.dart';
import 'live_perception_service.dart';
import 'obstacle_detection_screen.dart';

/// True wherever a camera pipeline can actually run (Android / iOS).
const bool obstacleDetectionSupported = true;

const String obstacleDetectionRoute = '/obstacle-detection';

Widget buildObstacleDetectionScreen(BuildContext context) =>
    const ObstacleDetectionScreen();

PerceptionService createLivePerceptionService(TtsService tts) =>
    LivePerceptionService(tts);
