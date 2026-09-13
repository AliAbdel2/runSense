import 'package:flutter/material.dart';

import '../../services/perception_service.dart';
import '../../services/tts_service.dart';

/// Web build: no camera pipeline. See `obstacle_detection_entry.dart`.
const bool obstacleDetectionSupported = false;

const String obstacleDetectionRoute = '/obstacle-detection';

Widget buildObstacleDetectionScreen(BuildContext context) =>
    const _UnsupportedScreen();

PerceptionService createLivePerceptionService(TtsService tts) =>
    throw UnsupportedError(
      'Camera-based obstacle detection requires Android or iOS. This build '
      'targets the web — keep useMock = true in lib/app_config.dart.',
    );

class _UnsupportedScreen extends StatelessWidget {
  const _UnsupportedScreen();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Obstacle Detection')),
      body: const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            'Obstacle detection needs the phone camera. Run this app on '
            'Android or iOS.',
            textAlign: TextAlign.center,
          ),
        ),
      ),
    );
  }
}
