import 'dart:io';

import 'package:camera/camera.dart';

/// Owns the physical camera and emits raw frames for processing.
class CameraService {
  CameraController? _controller;
  CameraDescription? _camera;

  CameraController? get controller => _controller;
  CameraDescription? get description => _camera;
  bool get isInitialized => _controller?.value.isInitialized ?? false;

  /// Call once before use. Picks the rear camera and starts it.
  Future<void> initialize() async {
    if (isInitialized) return;

    final cameras = await availableCameras();
    if (cameras.isEmpty) {
      throw CameraException('no_camera', 'This device has no usable camera.');
    }
    _camera = cameras.firstWhere(
      (c) => c.lensDirection == CameraLensDirection.back,
      orElse: () => cameras.first,
    );

    _controller = CameraController(
      _camera!,
      ResolutionPreset.medium, // medium is plenty; higher = slower, no benefit
      enableAudio: false,
      imageFormatGroup:
          Platform.isAndroid ? ImageFormatGroup.nv21 : ImageFormatGroup.bgra8888,
    );

    await _controller!.initialize();
  }

  /// Start delivering frames. The callback fires on EVERY frame — the caller
  /// throttles (see ObstacleDetectionController._onFrame).
  Future<void> startStream(void Function(CameraImage image) onFrame) async {
    if (!isInitialized) return;
    if (_controller!.value.isStreamingImages) return;
    await _controller!.startImageStream(onFrame);
  }

  Future<void> stopStream() async {
    if (_controller?.value.isStreamingImages ?? false) {
      await _controller!.stopImageStream();
    }
  }

  Future<void> dispose() async {
    await stopStream();
    await _controller?.dispose();
    _controller = null;
  }
}
