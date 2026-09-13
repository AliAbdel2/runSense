import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../models/alert.dart';
import '../models/location_fix.dart';
import '../models/session.dart';
import '../services/location_service.dart';
import '../services/mock/mock_session_service.dart';
import '../services/perception_service.dart';
import '../services/session_service.dart';
import '../services/tts_service.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../widgets/big_action_button.dart';
import 'session_summary_screen.dart';

/// Live Run screen (plan section 6.2): subscribes to
/// PerceptionService.alertStream(), speaks each alert, interrupts + haptics
/// on DANGER, and keeps an in-memory alert count for the end-of-session
/// summary (read by whoever builds that summary UI later).
class LiveRunScreen extends StatefulWidget {
  final String plannedSessionId;

  const LiveRunScreen({super.key, required this.plannedSessionId});

  @override
  State<LiveRunScreen> createState() => _LiveRunScreenState();
}

class _LiveRunScreenState extends State<LiveRunScreen> {
  StreamSubscription<ObstacleAlert>? _sub;
  StreamSubscription<LocationFix>? _locSub;
  String? _sessionId;
  ObstacleAlert? _lastAlert;
  int _alertCount = 0;
  bool _ending = false;

  LocationFix? _lastFix;
  double _distanceMeters = 0;
  DateTime? _startTime;

  // Cached at start rather than looked up again in dispose()/_endSession():
  // context.read() does an ancestor lookup, and calling it inside dispose()
  // is unsafe — by then (e.g. mid pushReplacement to SessionSummaryScreen)
  // this element can already be deactivated, which throws
  // "Looking up a deactivated widget's ancestor is unsafe."
  PerceptionService? _perception;
  LocationService? _location;

  @override
  void initState() {
    super.initState();
    _start();
  }

  Future<void> _start() async {
    final sessionService = context.read<SessionService>();
    final perception = context.read<PerceptionService>();
    final location = context.read<LocationService>();
    _perception = perception;
    _location = location;
    final completed = await sessionService.startSession(widget.plannedSessionId);
    if (!mounted) return;
    _sessionId = completed.sessionId;
    _sub = perception.alertStream().listen(_onAlert);
    perception.startSimulation();
    _startTime = DateTime.now();
    _locSub = location.positionStream().listen(_onFix);
    location.startTracking();
  }

  void _onAlert(ObstacleAlert alert) {
    if (!mounted) return;
    setState(() {
      _lastAlert = alert;
      _alertCount++;
    });
    final tts = context.read<TtsService>();
    if (alert.tier == AlertTier.danger) {
      HapticFeedback.heavyImpact();
      tts.interruptAndSpeak(alert.utterance);
    } else {
      tts.speak(alert.utterance);
    }
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
    final sessionId = _sessionId;
    if (sessionId != null) {
      await sessionService.endSession(sessionId);
    }
    if (!mounted) return;

    // MockSessionService.endSession() can't return the CompletedSession
    // directly (the SessionService interface locks it to Future<void> — see
    // the checkpoint-2 deviation note in PROGRESS.md), so this cast is the
    // documented way to read its adaptationNote. alertCount, actualKm and
    // duration are all this screen's own live-observed numbers now (from the
    // alert stream and LocationService), not the mock's hardcoded stand-ins.
    final mockCompleted =
        sessionService is MockSessionService ? sessionService.lastCompleted : null;
    final elapsed =
        _startTime == null ? Duration.zero : DateTime.now().difference(_startTime!);
    final summary = CompletedSession(
      sessionId: mockCompleted?.sessionId ?? sessionId ?? widget.plannedSessionId,
      actualKm: _distanceMeters / 1000,
      duration: elapsed,
      alertCount: _alertCount,
      adaptationNote: mockCompleted?.adaptationNote,
    );
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(builder: (_) => SessionSummaryScreen(session: summary)),
    );
  }

  @override
  void dispose() {
    _sub?.cancel();
    _locSub?.cancel();
    _perception?.stopSimulation();
    _location?.stopTracking();
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
