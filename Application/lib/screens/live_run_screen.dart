import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../features/obstacle_detection/obstacle_detection_entry.dart';
import '../models/alert.dart';
import '../models/location_fix.dart';
import '../models/session.dart';
import '../services/location_service.dart';
import '../services/mock/mock_session_service.dart';
import '../services/pace_coach.dart';
import '../services/perception_service.dart';
import '../services/run_narrator.dart';
import '../services/session_service.dart';
import '../services/tts_service.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../widgets/big_action_button.dart';
import 'session_summary_screen.dart';

/// Live Run screen (plan section 6.2): subscribes to
/// PerceptionService.alertStream(), narrates each alert/pace cue through
/// [RunNarrator], and keeps an in-memory alert count for the end-of-session
/// summary.
class LiveRunScreen extends StatefulWidget {
  final String plannedSessionId;

  /// From the briefed session's pace target — enables PaceCoach's off-pace
  /// nudge. Null (e.g. no target set) leaves periodic pace callouts only.
  final int? targetPaceSecPerKm;

  const LiveRunScreen({
    super.key,
    required this.plannedSessionId,
    this.targetPaceSecPerKm,
  });

  @override
  State<LiveRunScreen> createState() => _LiveRunScreenState();
}

class _LiveRunScreenState extends State<LiveRunScreen>
    with WidgetsBindingObserver {
  StreamSubscription<ObstacleAlert>? _sub;
  StreamSubscription<LocationFix>? _locSub;
  String? _sessionId;
  ObstacleAlert? _lastAlert;
  int _alertCount = 0;
  bool _ending = false;
  bool _obstacleDetectionPaused = false;

  LocationFix? _lastFix;
  double _distanceMeters = 0;
  DateTime? _startTime;

  late final PaceCoach _paceCoach =
      PaceCoach(targetPaceSecPerKm: widget.targetPaceSecPerKm);

  // Cached at start rather than looked up again in dispose()/_endSession():
  // context.read() does an ancestor lookup, and calling it inside dispose()
  // is unsafe — by then (e.g. mid pushReplacement to SessionSummaryScreen)
  // this element can already be deactivated, which throws
  // "Looking up a deactivated widget's ancestor is unsafe."
  PerceptionService? _perception;
  LocationService? _location;
  SessionService? _sessionService;
  RunNarrator? _narrator;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _start();
  }

  Future<void> _start() async {
    final sessionService = context.read<SessionService>();
    final perception = context.read<PerceptionService>();
    final location = context.read<LocationService>();
    _perception = perception;
    _location = location;
    _sessionService = sessionService;
    _narrator = RunNarrator(context.read<TtsService>());
    try {
      await WakelockPlus.enable().timeout(const Duration(seconds: 5));
    } catch (_) {
      // No platform channel (e.g. a test harness) or a plugin hang — the run
      // still works, it just won't keep the screen awake.
    }
    final completed = await sessionService.startSession(widget.plannedSessionId);
    if (!mounted) return;
    _sessionId = completed.sessionId;
    _sub = perception.alertStream().listen(_onAlert);
    perception.startSimulation();
    _startTime = DateTime.now();
    var locationGranted = false;
    try {
      locationGranted = await location
          .requestPermission()
          .timeout(const Duration(seconds: 10));
    } catch (_) {}
    if (locationGranted) {
      _locSub = location.positionStream().listen(_onFix);
      location.startTracking();
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final perception = _perception;
    final narrator = _narrator;
    if (perception == null || _ending) return;
    if (state != AppLifecycleState.resumed) {
      if (!_obstacleDetectionPaused) {
        _obstacleDetectionPaused = true;
        perception.stopSimulation();
        narrator?.announceSystem('Obstacle detection paused');
      }
    } else if (_obstacleDetectionPaused) {
      _obstacleDetectionPaused = false;
      perception.startSimulation();
      narrator?.announceSystem('Obstacle detection resumed');
    }
  }

  void _onAlert(ObstacleAlert alert) {
    if (!mounted) return;
    setState(() {
      _lastAlert = alert;
      _alertCount++;
    });
    _narrator?.announceObstacle(alert);
  }

  void _onFix(LocationFix fix) {
    if (!mounted) return;
    final previous = _lastFix;
    setState(() {
      if (previous != null) {
        _distanceMeters += _haversineMeters(previous, fix);
      }
      _lastFix = fix;
    });
    final sessionId = _sessionId;
    final sessionService = _sessionService;
    if (sessionId != null && sessionService != null) {
      unawaited(
        sessionService
            .addLocationSample(sessionId, fix)
            .catchError((_) {}),
      );
    }
    final paceUtterance = _paceCoach.onFix(fix);
    if (paceUtterance != null) {
      _narrator?.announcePace(paceUtterance);
    }
  }

  /// Great-circle distance between two fixes, in meters. Standard haversine
  /// formula — Earth radius taken as a mean 6,371,000m, plenty accurate for
  /// summing a run's short hops.
  double _haversineMeters(LocationFix a, LocationFix b) {
    const earthRadiusMeters = 6371000.0;
    final dLat = _degToRad(b.latitude - a.latitude);
    final dLon = _degToRad(b.longitude - a.longitude);
    final lat1 = _degToRad(a.latitude);
    final lat2 = _degToRad(b.latitude);
    final h = sin(dLat / 2) * sin(dLat / 2) +
        sin(dLon / 2) * sin(dLon / 2) * cos(lat1) * cos(lat2);
    return 2 * earthRadiusMeters * atan2(sqrt(h), sqrt(1 - h));
  }

  double _degToRad(double deg) => deg * pi / 180;

  String _formatElapsed(Duration d) {
    final minutes = d.inMinutes;
    final seconds = d.inSeconds % 60;
    return '$minutes:${seconds.toString().padLeft(2, '0')}';
  }

  Future<void> _endSession() async {
    if (_ending) return;
    setState(() => _ending = true);
    final sessionService = context.read<SessionService>();
    final tts = context.read<TtsService>();
    _perception?.stopSimulation();
    _location?.stopTracking();
    await tts.stop();
    try {
      await WakelockPlus.disable().timeout(const Duration(seconds: 5));
    } catch (_) {}
    final sessionId = _sessionId;
    final backendCompleted = sessionId == null
        ? null
        : await sessionService.endSession(sessionId);
    if (!mounted) return;

    // Mock sessions keep the canned adaptation note, while a live session uses
    // the backend's accepted GPS distance and active elapsed time. Alert count
    // remains local because obstacle inference intentionally stays on-device.
    final mockCompleted =
        sessionService is MockSessionService ? sessionService.lastCompleted : null;
    final elapsed =
        _startTime == null ? Duration.zero : DateTime.now().difference(_startTime!);
    final useBackendSummary = sessionService is! MockSessionService;
    final summary = CompletedSession(
      sessionId: mockCompleted?.sessionId ?? sessionId ?? widget.plannedSessionId,
      actualKm: useBackendSummary
          ? backendCompleted?.actualKm ?? _distanceMeters / 1000
          : _distanceMeters / 1000,
      duration: useBackendSummary
          ? backendCompleted?.duration ?? elapsed
          : elapsed,
      alertCount: _alertCount,
      adaptationNote: mockCompleted?.adaptationNote,
    );
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => SessionSummaryScreen(session: summary)),
    );
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _sub?.cancel();
    _locSub?.cancel();
    _perception?.stopSimulation();
    _location?.stopTracking();
    WakelockPlus.disable().catchError((_) {});
    super.dispose();
  }

  Color _tierColor(AlertTier tier) {
    switch (tier) {
      case AlertTier.danger:
        return AppSemanticColors.danger;
      case AlertTier.warning:
        return AppSemanticColors.warning;
      case AlertTier.notice:
        return AppSemanticColors.notice;
    }
  }

  IconData _tierIcon(AlertTier tier) {
    switch (tier) {
      case AlertTier.danger:
        return Icons.error;
      case AlertTier.warning:
        return Icons.warning_amber;
      case AlertTier.notice:
        return Icons.info_outline;
    }
  }

  String _zoneLabel(Zone zone) {
    switch (zone) {
      case Zone.left:
        return 'LEFT';
      case Zone.center:
        return 'CENTER';
      case Zone.right:
        return 'RIGHT';
    }
  }

  String _distanceLabel(Distance distance) {
    switch (distance) {
      case Distance.near:
        return 'NEAR';
      case Distance.mid:
        return 'MID';
      case Distance.far:
        return 'FAR';
    }
  }

  String _tierLabel(AlertTier tier) {
    switch (tier) {
      case AlertTier.danger:
        return 'DANGER';
      case AlertTier.warning:
        return 'WARNING';
      case AlertTier.notice:
        return 'NOTICE';
    }
  }

  @override
  Widget build(BuildContext context) {
    final alert = _lastAlert;
    final panelColor = alert == null ? AppSemanticColors.idle : _tierColor(alert.tier);
    final panelText = alert == null
        ? 'All clear'
        : '${_tierLabel(alert.tier)} · ${_zoneLabel(alert.zone)} · ${_distanceLabel(alert.distance)}';
    final panelSemantics = alert == null
        ? 'All clear, no obstacles detected'
        : '${_tierLabel(alert.tier)} alert. ${alert.utterance}';
    final motionDuration = MediaQuery.of(context).disableAnimations
        ? Duration.zero
        : const Duration(milliseconds: 220);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Live Run'),
        // Custom leading, not AccessibleBackButton: leaving via the back
        // arrow should end the session the same way "END SESSION" does
        // (stop simulation/TTS, record the CompletedSession) rather than a
        // bare pop.
        leading: Semantics(
          button: true,
          label: 'End session and go back',
          child: IconButton(
            icon: const Icon(Icons.arrow_back),
            constraints: const BoxConstraints(minWidth: 64, minHeight: 64),
            onPressed: _ending ? null : _endSession,
          ),
        ),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Builder(builder: (context) {
                final perception = _perception;
                final preview =
                    perception == null ? null : buildRunCameraPreview(perception);
                // Degrades cleanly to nothing when there's no live camera
                // (mock service, or not yet initialized).
                if (preview == null) return const SizedBox.shrink();
                return Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.md),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(14),
                    child: AspectRatio(aspectRatio: 3 / 4, child: preview),
                  ),
                );
              }),
              Expanded(
                child: Semantics(
                  liveRegion: true,
                  label: panelSemantics,
                  child: AnimatedContainer(
                    duration: motionDuration,
                    curve: Curves.easeOutCubic,
                    decoration: BoxDecoration(
                      color: panelColor,
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: AnimatedSwitcher(
                      duration: motionDuration,
                      switchInCurve: Curves.easeOutCubic,
                      child: Column(
                        key: ValueKey(alert?.tier ?? 'idle'),
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(
                            alert == null
                                ? Icons.check_circle_outline
                                : _tierIcon(alert.tier),
                            color: AppSemanticColors.onFill,
                            size: 96,
                          ),
                          const SizedBox(height: AppSpacing.md),
                          Text(
                            panelText,
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                              color: AppSemanticColors.onFill,
                              fontSize: 26,
                              fontWeight: FontWeight.w700,
                              letterSpacing: -0.2,
                            ),
                          ),
                          if (alert != null) ...[
                            const SizedBox(height: AppSpacing.sm),
                            Text(
                              alert.utterance,
                              textAlign: TextAlign.center,
                              style: const TextStyle(
                                color: AppSemanticColors.onFill,
                                fontSize: 17,
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              Builder(builder: (context) {
                final elapsed = _startTime == null
                    ? Duration.zero
                    : DateTime.now().difference(_startTime!);
                final km = (_distanceMeters / 1000).toStringAsFixed(2);
                return Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.md,
                    vertical: AppSpacing.sm,
                  ),
                  decoration: BoxDecoration(
                    color: Theme.of(context).panelColor,
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                    children: [
                      _RunStat(
                        icon: Icons.report_outlined,
                        value: '$_alertCount',
                        label: 'alerts',
                      ),
                      _RunStat(icon: Icons.route, value: '$km km', label: 'distance'),
                      _RunStat(
                        icon: Icons.timer_outlined,
                        value: _formatElapsed(elapsed),
                        label: 'elapsed',
                      ),
                    ],
                  ),
                );
              }),
              const SizedBox(height: AppSpacing.md),
              BigActionButton(
                label: _ending ? 'ENDING…' : 'END SESSION',
                semanticLabel: 'End session',
                onPressed: _ending ? null : _endSession,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _RunStat extends StatelessWidget {
  final IconData icon;
  final String value;
  final String label;

  const _RunStat({required this.icon, required this.value, required this.label});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: '$label $value',
      excludeSemantics: true,
      child: Column(
        children: [
          Icon(icon, size: 20, color: Theme.of(context).colorScheme.primary),
          const SizedBox(height: 2),
          Text(
            value,
            style: Theme.of(context)
                .textTheme
                .titleMedium
                ?.copyWith(fontWeight: FontWeight.w700),
          ),
          Text(label, style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}
