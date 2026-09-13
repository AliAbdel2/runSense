import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/session.dart';
import '../services/agent_chat_service.dart';
import '../services/plan_service.dart';
import '../services/tts_service.dart';
import '../widgets/big_action_button.dart';
import 'live_run_screen.dart';
import 'week_plan_screen.dart';

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
    final tts = context.read<TtsService>();
    await tts.speak('Starting session: ${today.description}');
    if (!mounted) return;
    // LiveRunScreen calls SessionService.startSession() itself once pushed.
    await Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => LiveRunScreen(plannedSessionId: today.id)),
    );
    // Ending the run can leave the plan in a different state (e.g. a replan
    // happened, or a future checkpoint has endSession() adapt tomorrow's
    // session) — reload so Home always shows the current plan on return.
    if (!mounted) return;
    await _loadAndAnnounce();
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

  Future<void> _openWeekPlan() async {
    await Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const WeekPlanScreen()),
    );
    // A long-press replan on the Week Plan screen may have changed today's
    // entry (e.g. Tue's guide got cancelled) — reload so Home reflects it.
    if (!mounted) return;
    await _loadAndAnnounce();
  }

  @override
  Widget build(BuildContext context) {
    final today = _today;
    return Scaffold(
      appBar: AppBar(
        title: const Text('RunSense'),
        actions: [
          Semantics(
            button: true,
            label: 'Week plan',
            child: IconButton(
              icon: const Icon(Icons.calendar_view_week),
              tooltip: 'Week plan',
              constraints: const BoxConstraints(minWidth: 64, minHeight: 64),
              onPressed: _openWeekPlan,
            ),
          ),
        ],
      ),
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
                      Semantics(
                        liveRegion: true,
                        child: Text(_coachReply!,
                            style: Theme.of(context).textTheme.bodyLarge),
                      ),
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
                  ],
                ),
        ),
      ),
    );
  }
}
