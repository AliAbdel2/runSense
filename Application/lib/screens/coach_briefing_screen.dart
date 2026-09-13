import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:provider/provider.dart';

import '../models/session.dart';
import '../services/agent_chat_service.dart';
import '../services/tts_service.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../widgets/accessible_back_button.dart';
import '../widgets/big_action_button.dart';
import '../widgets/session_type_badge.dart';
import 'live_run_screen.dart';

enum _BriefingState { loading, ready, error }

/// Sits between Home and Live Run: the runner asks what today's session is,
/// the (mocked) coach briefs them, and confirming here starts the run. Facts
/// (what/where) always come from [session] so they're never wrong even
/// though the coach's reply is currently canned — that split is what keeps
/// this honest once a real LLM sits behind AgentChatService.
class CoachBriefingScreen extends StatefulWidget {
  final PlannedSession session;

  const CoachBriefingScreen({super.key, required this.session});

  @override
  State<CoachBriefingScreen> createState() => _CoachBriefingScreenState();
}

class _CoachBriefingScreenState extends State<CoachBriefingScreen> {
  _BriefingState _state = _BriefingState.loading;
  String? _coachReply;

  @override
  void initState() {
    super.initState();
    _loadBriefing();
  }

  Future<void> _loadBriefing() async {
    final tts = context.read<TtsService>();
    final agent = context.read<AgentChatService>();
    final session = widget.session;

    await tts.interruptAndSpeak('Asking your coach');

    final question = "What's my workout today? "
        "It's ${session.description} at ${session.venue}.";

    String? reply;
    var errored = false;
    try {
      reply = await agent.sendMessage(question);
    } catch (_) {
      errored = true;
    }

    if (!mounted) return;
    setState(() {
      _coachReply = reply;
      _state = errored ? _BriefingState.error : _BriefingState.ready;
    });

    final toSpeak = errored
        ? "${session.spokenSummary} I couldn't reach your coach, but you can "
            "still start."
        : '${session.spokenSummary} ${reply ?? ''}';
    await tts.speak(toSpeak);
  }

  Future<void> _startRun() async {
    final tts = context.read<TtsService>();
    var granted = false;
    try {
      granted = (await Permission.camera
              .request()
              .timeout(const Duration(seconds: 5)))
          .isGranted;
    } catch (_) {
      // No platform channel (e.g. running in a test harness), a hang, or the
      // plugin itself failing — treat exactly like a denial below.
      granted = false;
    }
    if (!granted) {
      await tts.speak('Obstacle alerts are off. Starting your run.');
    }
    if (!mounted) return;
    await Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (_) => LiveRunScreen(
          plannedSessionId: widget.session.id,
          targetPaceSecPerKm: widget.session.effectiveTargetPaceSecPerKm,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final session = widget.session;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Coach Briefing'),
        leading: const AccessibleBackButton(),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SessionTypeBadge(
                type: session.type,
                color: Theme.of(context).colorScheme.primary,
              ),
              const SizedBox(height: AppSpacing.md),
              Semantics(
                liveRegion: true,
                child: Text(
                  session.spokenSummary,
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                '${session.description} · ${session.venue}',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
              const SizedBox(height: AppSpacing.lg),
              if (_state == _BriefingState.loading)
                const Center(child: CircularProgressIndicator())
              else
                Semantics(
                  liveRegion: true,
                  child: Container(
                    padding: const EdgeInsets.all(AppSpacing.md),
                    decoration: BoxDecoration(
                      color: Theme.of(context).panelColor,
                      borderRadius: BorderRadius.circular(14),
                    ),
                    child: Text(
                      _state == _BriefingState.error
                          ? "Couldn't reach your coach, but you can still start."
                          : _coachReply ?? '',
                      style: Theme.of(context).textTheme.bodyLarge,
                    ),
                  ),
                ),
              const Spacer(),
              BigActionButton(
                label: 'START RUN',
                semanticLabel: 'Start run',
                onPressed: _state == _BriefingState.loading ? null : _startRun,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
