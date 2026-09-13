import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../features/obstacle_detection/obstacle_detection_entry.dart';
import '../models/session.dart';
import '../services/agent_chat_service.dart';
import '../services/plan_service.dart';
import '../services/session_service.dart';
import '../services/tts_service.dart';
import '../widgets/big_action_button.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  PlannedSession? _today;
  bool _loading = true;
  bool _askingCoach = false;
  String? _coachReply;

  @override
  void initState() {
    super.initState();
    _loadAndAnnounce();
  }

  Future<void> _loadAndAnnounce() async {
    final plan = context.read<PlanService>();
    final tts = context.read<TtsService>();
    final week = await plan.getWeekPlan('sara-1');
    final today = _pickToday(week);
    if (!mounted) return;
    setState(() {
      _today = today;
      _loading = false;
    });
    if (today != null) {
      await tts.speak(today.spokenSummary);
    }
  }

  PlannedSession? _pickToday(List<PlannedSession> week) {
    if (week.isEmpty) return null;
    final todayIso = DateTime.now().toIso8601String().substring(0, 10);
    for (final s in week) {
      if (s.date == todayIso) return s;
    }
    return week.first; // fallback for the demo if today isn't in the mocked week
  }

  Future<void> _startSession() async {
    final today = _today;
    if (today == null) return;
    final sessionService = context.read<SessionService>();
    final tts = context.read<TtsService>();
    await sessionService.startSession(today.id);
    await tts.speak('Starting session: ${today.description}');
    // TODO(checkpoint 6): navigate to the Live Run screen once it exists.
  }

  Future<void> _askCoach() async {
    final agent = context.read<AgentChatService>();
    final tts = context.read<TtsService>();
    setState(() => _askingCoach = true);
    await tts.speak('Listening');
    // No speech-to-text yet — simulate a recognized phrase for the demo.
    const heard = 'Plan my week, guide only Tuesday and Saturday';
    final reply = await agent.sendMessage(heard);
    if (!mounted) return;
    setState(() {
      _askingCoach = false;
      _coachReply = reply;
    });
    await tts.speak(reply);
  }

  @override
  Widget build(BuildContext context) {
    final today = _today;
    return Scaffold(
      appBar: AppBar(title: const Text('RunSense')),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Semantics(
                      liveRegion: true,
                      child: Text(
                        today?.spokenSummary ?? 'No session scheduled today.',
                        style: Theme.of(context).textTheme.headlineSmall,
                      ),
                    ),
                    const SizedBox(height: 8),
                    if (today != null)
                      Text(
                        '${today.description} · ${today.venue}',
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                    const Spacer(),
                    if (_coachReply != null) ...[
                      Text(_coachReply!,
                          style: Theme.of(context).textTheme.bodyLarge),
                      const SizedBox(height: 16),
                    ],
                    BigActionButton(
                      label: 'START SESSION',
                      semanticLabel: 'Start session',
                      onPressed: today == null || today.type == SessionType.rest
                          ? null
                          : _startSession,
                    ),
                    const SizedBox(height: 16),
                    BigActionButton(
                      label: _askingCoach ? 'LISTENING…' : 'ASK COACH',
                      semanticLabel: 'Ask coach',
                      primary: false,
                      onPressed: _askingCoach ? null : _askCoach,
                    ),
                    if (obstacleDetectionSupported) ...[
                      const SizedBox(height: 16),
                      BigActionButton(
                        label: 'OBSTACLE DETECTION',
                        semanticLabel: 'Open obstacle detection',
                        primary: false,
                        onPressed: () => Navigator.of(context)
                            .pushNamed(obstacleDetectionRoute),
                      ),
                    ],
                  ],
                ),
        ),
      ),
    );
  }
}
