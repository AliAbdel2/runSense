import 'package:flutter/material.dart';

import '../models/session.dart';
import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../widgets/big_action_button.dart';

/// Shown after "End session" on the Live Run screen. Reads whatever
/// SessionService.endSession() produced (see LiveRunScreen._endSession) —
/// nothing here is mocked itself, it just displays the CompletedSession.
class SessionSummaryScreen extends StatelessWidget {
  final CompletedSession session;

  const SessionSummaryScreen({super.key, required this.session});

  String _formatDuration(Duration d) {
    final minutes = d.inMinutes;
    final seconds = d.inSeconds % 60;
    return '$minutes min ${seconds.toString().padLeft(2, '0')} sec';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Session Summary'), automaticallyImplyLeading: false),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Icon(
                    Icons.check_circle,
                    color: AppSemanticColors.accepted,
                    size: 32,
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: Semantics(
                      liveRegion: true,
                      child: Text(
                        'Session complete',
                        style: Theme.of(context).textTheme.headlineSmall,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.lg),
              Container(
                padding: const EdgeInsets.all(AppSpacing.md),
                decoration: BoxDecoration(
                  color: Theme.of(context).panelColor,
                  borderRadius: BorderRadius.circular(16),
                ),
                child: Column(
                  children: [
                    _StatRow(
                      icon: Icons.route,
                      label: 'Distance',
                      value: '${session.actualKm.toStringAsFixed(2)} km',
                    ),
                    Divider(height: AppSpacing.lg, color: Theme.of(context).borderColor),
                    _StatRow(
                      icon: Icons.timer_outlined,
                      label: 'Duration',
                      value: _formatDuration(session.duration),
                    ),
                    Divider(height: AppSpacing.lg, color: Theme.of(context).borderColor),
                    _StatRow(
                      icon: Icons.report_outlined,
                      label: 'Alerts',
                      value: '${session.alertCount}',
                    ),
                  ],
                ),
              ),
              if (session.adaptationNote != null) ...[
                const SizedBox(height: AppSpacing.md),
                Semantics(
                  liveRegion: true,
                  child: Container(
                    padding: const EdgeInsets.all(AppSpacing.md),
                    decoration: BoxDecoration(
                      color: AppSemanticColors.notice,
                      borderRadius: BorderRadius.circular(14),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.autorenew, color: AppSemanticColors.onFill),
                        const SizedBox(width: AppSpacing.sm),
                        Expanded(
                          child: Text(
                            session.adaptationNote!,
                            style: const TextStyle(color: AppSemanticColors.onFill),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
              const Spacer(),
              BigActionButton(
                label: 'DONE',
                semanticLabel: 'Done, back to home',
                onPressed: () => Navigator.of(context).pop(),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _StatRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;

  const _StatRow({required this.icon, required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: '$label: $value',
      excludeSemantics: true,
      child: Row(
        children: [
          Icon(icon, size: 20, color: Theme.of(context).colorScheme.primary),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(label, style: Theme.of(context).textTheme.bodyLarge),
          ),
          Text(
            value,
            style: Theme.of(context)
                .textTheme
                .bodyLarge
                ?.copyWith(fontWeight: FontWeight.bold, color: Theme.of(context).colorScheme.onSurface),
          ),
        ],
      ),
    );
  }
}
