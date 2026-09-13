import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:provider/provider.dart';

import '../models/session.dart';
import '../services/plan_service.dart';
import '../services/tts_service.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../widgets/accessible_back_button.dart';
import '../widgets/guide_status_chip.dart';
import '../widgets/session_type_badge.dart';

/// Week Plan screen (plan section 6.3): read-only list of PlannedSessions,
/// one sentence each, a GuideStatusChip, and a long-press to trigger
/// PlanService.requestReplan().
class WeekPlanScreen extends StatefulWidget {
  const WeekPlanScreen({super.key});

  @override
  State<WeekPlanScreen> createState() => _WeekPlanScreenState();
}

class _WeekPlanScreenState extends State<WeekPlanScreen> {
  List<PlannedSession> _week = [];
  bool _loading = true;
  bool _replanning = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final plan = context.read<PlanService>();
    final week = await plan.getWeekPlan('sara-1');
    if (!mounted) return;
    setState(() {
      _week = week;
      _loading = false;
    });
  }

  Future<void> _requestReplan(PlannedSession session) async {
    if (_replanning) return;
    setState(() => _replanning = true);
    final plan = context.read<PlanService>();
    final tts = context.read<TtsService>();
    await plan.requestReplan('Guide cancelled: ${session.description}');
    final week = await plan.getWeekPlan('sara-1');
    if (!mounted) return;
    setState(() {
      _week = week;
      _replanning = false;
    });
    await tts.speak('Your week has been updated.');
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Week plan updated.')),
    );
  }

  String _typeLabel(SessionType type) {
    switch (type) {
      case SessionType.easy:
        return 'Easy';
      case SessionType.hard:
        return 'Hard';
      case SessionType.longRun:
        return 'Long run';
      case SessionType.rest:
        return 'Rest';
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Week Plan'), leading: const AccessibleBackButton()),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : Stack(
                children: [
                  ListView.separated(
                    padding: const EdgeInsets.all(AppSpacing.md),
                    itemCount: _week.length,
                    separatorBuilder: (_, _) => const SizedBox(height: AppSpacing.sm),
                    itemBuilder: (context, index) {
                      final session = _week[index];
                      return Semantics(
                        button: true,
                        label:
                            '${session.date}, ${_typeLabel(session.type)}. ${session.description}. Long press to request a replan.',
                        customSemanticsActions: _replanning
                            ? null
                            : {
                                const CustomSemanticsAction(label: 'Request replan'):
                                    () => _requestReplan(session),
                              },
                        child: InkWell(
                          onLongPress: _replanning ? null : () => _requestReplan(session),
                          borderRadius: BorderRadius.circular(14),
                          child: Container(
                            constraints: const BoxConstraints(minHeight: 64),
                            padding: const EdgeInsets.all(AppSpacing.md),
                            decoration: BoxDecoration(
                              color: Theme.of(context).panelColor,
                              border: Border.all(color: Theme.of(context).borderColor),
                              borderRadius: BorderRadius.circular(14),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    Expanded(
                                      child: Text(
                                        session.date,
                                        style: Theme.of(context)
                                            .textTheme
                                            .titleMedium
                                            ?.copyWith(fontWeight: FontWeight.bold),
                                      ),
                                    ),
                                    GuideStatusChip(status: session.guideStatus),
                                  ],
                                ),
                                const SizedBox(height: AppSpacing.xs),
                                SessionTypeBadge(type: session.type),
                                const SizedBox(height: AppSpacing.xs),
                                Text(
                                  session.description,
                                  style: Theme.of(context).textTheme.bodyLarge,
                                ),
                              ],
                            ),
                          ),
                        ),
                      );
                    },
                  ),
                  if (_replanning)
                    Container(
                      color: Theme.of(context).colorScheme.onSurface.withValues(alpha: 0.15),
                      child: const Center(child: CircularProgressIndicator()),
                    ),
                ],
              ),
      ),
    );
  }
}
