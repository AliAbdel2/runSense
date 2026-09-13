import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../models/alert.dart';
import '../models/session.dart';
import '../services/mock/mock_session_service.dart';
import '../services/perception_service.dart';
import '../services/session_service.dart';
import '../services/tts_service.dart';
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
  String? _sessionId;
  ObstacleAlert? _lastAlert;
  int _alertCount = 0;
  bool _ending = false;

  @override
  void initState() {
    super.initState();
    _start();
  }

  Future<void> _start() async {
    final sessionService = context.read<SessionService>();
    final perception = context.read<PerceptionService>();
    final completed = await sessionService.startSession(widget.plannedSessionId);
    if (!mounted) return;
    _sessionId = completed.sessionId;
    _sub = perception.alertStream().listen(_onAlert);
    perception.startSimulation();
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

  Future<void> _endSession() async {
    if (_ending) return;
    setState(() => _ending = true);
    final sessionService = context.read<SessionService>();
    final perception = context.read<PerceptionService>();
    final tts = context.read<TtsService>();
    perception.stopSimulation();
    await tts.stop();
    final sessionId = _sessionId;
    if (sessionId != null) {
      await sessionService.endSession(sessionId);
    }
    if (!mounted) return;

    // MockSessionService.endSession() can't return the CompletedSession
    // directly (the SessionService interface locks it to Future<void> — see
    // the checkpoint-2 deviation note in PROGRESS.md), so this cast is the
    // documented way to read it. alertCount is overridden with what this
    // screen actually observed rather than the mock's hardcoded value, since
    // that number is real; distance/duration stay mocked until a
    // LiveLocationService exists to measure them for real.
    final mockCompleted =
        sessionService is MockSessionService ? sessionService.lastCompleted : null;
    final summary = CompletedSession(
      sessionId: mockCompleted?.sessionId ?? sessionId ?? widget.plannedSessionId,
      actualKm: mockCompleted?.actualKm ?? 0.0,
      duration: mockCompleted?.duration ?? Duration.zero,
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
    context.read<PerceptionService>().stopSimulation();
    super.dispose();
  }

  Color _tierColor(AlertTier tier) {
    switch (tier) {
      case AlertTier.danger:
        return Colors.red.shade700;
      case AlertTier.warning:
        return Colors.orange.shade700;
      case AlertTier.notice:
        return Colors.amber.shade700;
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
    final panelColor = alert == null ? Colors.grey.shade700 : _tierColor(alert.tier);
    final panelText = alert == null
        ? 'All clear'
        : '${_tierLabel(alert.tier)} · ${_zoneLabel(alert.zone)} · ${_distanceLabel(alert.distance)}';
    final panelSemantics = alert == null
        ? 'All clear, no obstacles detected'
        : '${_tierLabel(alert.tier)} alert. ${alert.utterance}';

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
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(
                child: Semantics(
                  liveRegion: true,
                  label: panelSemantics,
                  child: Container(
                    decoration: BoxDecoration(
                      color: panelColor,
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(
                          alert == null ? Icons.check_circle_outline : _tierIcon(alert.tier),
                          color: Colors.white,
                          size: 96,
                        ),
                        const SizedBox(height: 16),
                        Text(
                          panelText,
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 28,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        if (alert != null) ...[
                          const SizedBox(height: 8),
                          Text(
                            alert.utterance,
                            textAlign: TextAlign.center,
                            style: const TextStyle(color: Colors.white, fontSize: 18),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 16),
              Semantics(
                label: 'Alerts this session: $_alertCount',
                child: Text(
                  'Alerts this session: $_alertCount',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
              ),
              const SizedBox(height: 16),
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
