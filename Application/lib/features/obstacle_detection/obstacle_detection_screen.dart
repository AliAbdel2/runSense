import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:provider/provider.dart';

import '../../services/tts_service.dart';
import '../../widgets/big_action_button.dart';
import 'models/detected_obstacle.dart';
import 'models/obstacle_alert.dart';
import 'obstacle_detection_controller.dart';

/// Standalone obstacle-detection screen (module plan §9).
///
/// Deliberately minimal: the primary user can't see it. The preview is there
/// for a sighted tester/spotter, and everything interactive carries a
/// [Semantics] label so TalkBack/VoiceOver can drive it.
class ObstacleDetectionScreen extends StatelessWidget {
  const ObstacleDetectionScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (ctx) =>
          ObstacleDetectionController(tts: ctx.read<TtsService>()),
      child: const _ObstacleDetectionView(),
    );
  }
}

class _ObstacleDetectionView extends StatefulWidget {
  const _ObstacleDetectionView();

  @override
  State<_ObstacleDetectionView> createState() => _ObstacleDetectionViewState();
}

class _ObstacleDetectionViewState extends State<_ObstacleDetectionView>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Streaming frames while backgrounded crashes the camera plugin on both
    // platforms — stand down instead.
    if (state != AppLifecycleState.resumed) {
      final controller = context.read<ObstacleDetectionController>();
      if (controller.isRunning) controller.stop();
    }
  }

  Future<bool> _ensurePermission() async {
    final status = await Permission.camera.request();
    return status.isGranted;
  }

  Future<void> _toggle() async {
    final controller = context.read<ObstacleDetectionController>();
    if (controller.isRunning) {
      await controller.stop();
      return;
    }
    if (await _ensurePermission()) {
      await controller.start();
    } else {
      await controller.feedback.announce(
        'Camera permission is needed to detect obstacles',
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<ObstacleDetectionController>();
    final busy = controller.isStarting;

    return Scaffold(
      appBar: AppBar(title: const Text('Obstacle Detection')),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: controller.camera.isInitialized
                  ? CameraPreview(controller.camera.controller!)
                  : Center(
                      child: Text(
                        controller.error ?? 'Camera off',
                        textAlign: TextAlign.center,
                        style: Theme.of(context).textTheme.bodyLarge,
                      ),
                    ),
            ),
            Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // Sighted-spotter readout. The blind runner gets this as
                  // speech + haptics; this is here so a tester can see what
                  // the pipeline thinks is happening.
                  Semantics(
                    liveRegion: true,
                    child: Text(
                      _statusLine(controller),
                      style: Theme.of(context).textTheme.bodyLarge,
                    ),
                  ),
                  const SizedBox(height: 16),
                  BigActionButton(
                    label: busy
                        ? 'STARTING…'
                        : controller.isRunning
                            ? 'STOP'
                            : 'START',
                    semanticLabel: controller.isRunning
                        ? 'Stop obstacle detection'
                        : 'Start obstacle detection',
                    onPressed: busy ? null : _toggle,
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  String _statusLine(ObstacleDetectionController controller) {
    if (controller.error != null) return controller.error!;
    if (controller.isStarting) return 'Starting camera…';
    if (!controller.isRunning) return 'Detection stopped.';
    final alert = controller.lastAlert;
    if (alert == null) return 'Detection running. Path clear.';
    return '${_urgencyWord(alert.urgency)}: '
        '${alert.label} ${_directionWord(alert.direction)}';
  }

  String _urgencyWord(AlertUrgency u) {
    switch (u) {
      case AlertUrgency.none:
        return 'Clear';
      case AlertUrgency.low:
        return 'Notice';
      case AlertUrgency.medium:
        return 'Warning';
      case AlertUrgency.high:
        return 'DANGER';
    }
  }

  String _directionWord(ObstacleDirection d) {
    switch (d) {
      case ObstacleDirection.left:
        return 'left';
      case ObstacleDirection.right:
        return 'right';
      case ObstacleDirection.center:
        return 'ahead';
    }
  }
}
